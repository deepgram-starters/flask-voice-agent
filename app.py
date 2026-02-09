"""
Flask Voice Agent Starter - Backend Server

Simple WebSocket proxy to Deepgram's Voice Agent API.
Forwards all messages (JSON and binary) bidirectionally between client and Deepgram.

API Endpoints:
- WS /api/voice-agent - WebSocket proxy to Deepgram Voice Agent API
- GET /api/session - JWT session token endpoint
- GET /api/metadata - Application metadata
"""

import functools
import json
import os
import secrets
import threading
import time

import jwt
from flask import Flask, jsonify, make_response, request, send_from_directory
from flask_sock import Sock
from flask_cors import CORS
import websocket
import toml
from dotenv import load_dotenv

# Load .env file (won't override existing environment variables)
load_dotenv(override=False)

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    'deepgram_api_key': os.environ.get('DEEPGRAM_API_KEY'),
    'deepgram_agent_url': 'wss://agent.deepgram.com/v1/agent/converse',
    'port': int(os.environ.get('PORT', 8081)),
    'host': os.environ.get('HOST', '0.0.0.0'),
}

# Validate required environment variables
if not CONFIG['deepgram_api_key']:
    print("\n" + "="*70)
    print("ERROR: Deepgram API key not found!")
    print("="*70)
    print("\nPlease set your API key using one of these methods:")
    print("\n1. Create a .env file (recommended):")
    print("   DEEPGRAM_API_KEY=your_api_key_here")
    print("\n2. Environment variable:")
    print("   export DEEPGRAM_API_KEY=your_api_key_here")
    print("\nGet your API key at: https://console.deepgram.com")
    print("="*70 + "\n")
    exit(1)

# ============================================================================
# SESSION AUTH - JWT tokens with page nonce for production security
# ============================================================================

SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
REQUIRE_NONCE = bool(os.environ.get("SESSION_SECRET"))

# In-memory nonce store: nonce -> expiry timestamp
session_nonces = {}
NONCE_TTL = 5 * 60  # 5 minutes
JWT_EXPIRY = 3600  # 1 hour


def generate_nonce():
    """Generates a single-use nonce and stores it with an expiry."""
    nonce = secrets.token_hex(16)
    session_nonces[nonce] = time.time() + NONCE_TTL
    return nonce


def consume_nonce(nonce):
    """Validates and consumes a nonce (single-use). Returns True if valid."""
    expiry = session_nonces.pop(nonce, None)
    if expiry is None:
        return False
    return time.time() < expiry


def cleanup_nonces():
    """Remove expired nonces."""
    now = time.time()
    expired = [k for k, v in session_nonces.items() if now >= v]
    for k in expired:
        del session_nonces[k]


# Read frontend/dist/index.html template for nonce injection
_index_html_template = None
try:
    with open(os.path.join(os.path.dirname(__file__), "frontend", "dist", "index.html")) as f:
        _index_html_template = f.read()
except FileNotFoundError:
    pass  # No built frontend (dev mode)


def validate_ws_token():
    """Validates JWT from Sec-WebSocket-Protocol: access_token.<jwt> header."""
    protocol_header = request.headers.get("Sec-WebSocket-Protocol", "")
    protocols = [p.strip() for p in protocol_header.split(",")]
    token_proto = next((p for p in protocols if p.startswith("access_token.")), None)
    if not token_proto:
        return None
    token = token_proto[len("access_token."):]
    try:
        jwt.decode(token, SESSION_SECRET, algorithms=["HS256"])
        return token_proto
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

# ============================================================================
# SETUP - Initialize Flask, WebSocket, and CORS
# ============================================================================

# Initialize Flask app (API server only)
app = Flask(__name__)

# Enable CORS for frontend communication
CORS(app)

# Initialize native WebSocket support
sock = Sock(app)

# ============================================================================
# SESSION ROUTES - Auth endpoints (unprotected)
# ============================================================================

@app.route("/", methods=["GET"])
def serve_index():
    """Serve index.html with injected session nonce (production only)."""
    if not _index_html_template:
        return "Frontend not built. Run make build first.", 404
    cleanup_nonces()
    nonce = generate_nonce()
    html = _index_html_template.replace(
        "</head>",
        f'<meta name="session-nonce" content="{nonce}">\n</head>'
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html"
    return response


@app.route("/api/session", methods=["GET"])
def get_session():
    """Issues a JWT. In production, requires valid nonce via X-Session-Nonce header."""
    if REQUIRE_NONCE:
        nonce = request.headers.get("X-Session-Nonce")
        if not nonce or not consume_nonce(nonce):
            return jsonify({
                "error": {
                    "type": "AuthenticationError",
                    "code": "INVALID_NONCE",
                    "message": "Valid session nonce required. Please refresh the page.",
                }
            }), 403

    token = jwt.encode(
        {"iat": int(time.time()), "exp": int(time.time()) + JWT_EXPIRY},
        SESSION_SECRET,
        algorithm="HS256",
    )
    return jsonify({"token": token})


# ============================================================================
# API ROUTES
# ============================================================================

@app.route('/api/metadata')
def metadata():
    """Returns metadata about this starter application from deepgram.toml"""
    try:
        with open('deepgram.toml', 'r') as f:
            config = toml.load(f)

        if 'meta' not in config:
            return jsonify({
                'error': 'INTERNAL_SERVER_ERROR',
                'message': 'Missing [meta] section in deepgram.toml'
            }), 500

        return jsonify(config['meta'])
    except Exception as error:
        print(f'Error reading metadata: {error}')
        return jsonify({
            'error': 'INTERNAL_SERVER_ERROR',
            'message': 'Failed to read metadata from deepgram.toml'
        }), 500


# ============================================================================
# WEBSOCKET ENDPOINT - Voice Agent (Simple Pass-Through Proxy)
# ============================================================================

@sock.route('/api/voice-agent')
def voice_agent(ws):
    """
    WebSocket endpoint for voice agent conversations
    Simple pass-through proxy - forwards all messages bidirectionally
    """
    # Validate JWT from WebSocket subprotocol
    valid_proto = validate_ws_token()
    if not valid_proto:
        ws.close(4401, "Unauthorized")
        return

    print('Client connected to /api/voice-agent')

    # Thread control
    stop_event = threading.Event()
    deepgram_ws = None

    def forward_from_deepgram():
        """Thread to forward messages from Deepgram to client"""
        try:
            while not stop_event.is_set() and deepgram_ws:
                try:
                    # Receive from Deepgram (with timeout to check stop_event)
                    deepgram_ws.settimeout(1.0)
                    message = deepgram_ws.recv()

                    if message:
                        # Forward to client (preserves binary/text)
                        ws.send(message)
                except websocket.WebSocketTimeoutException:
                    # Timeout is normal - just check stop_event and continue
                    continue
                except Exception as e:
                    if not stop_event.is_set():
                        print(f'Error receiving from Deepgram: {e}')
                    break
        finally:
            stop_event.set()

    try:
        # Validate API key
        if not CONFIG['deepgram_api_key']:
            ws.send(json.dumps({
                'type': 'Error',
                'description': 'Missing API key',
                'code': 'MISSING_API_KEY'
            }))
            return

        # Create raw WebSocket connection to Deepgram Agent API
        print('Initiating Deepgram connection...')
        deepgram_ws = websocket.create_connection(
            CONFIG['deepgram_agent_url'],
            header=[f"Authorization: Token {CONFIG['deepgram_api_key']}"],
            timeout=10
        )
        print('✓ Connected to Deepgram Agent API')

        # Start thread to forward Deepgram → Client
        forward_thread = threading.Thread(target=forward_from_deepgram, daemon=True)
        forward_thread.start()

        # Main loop: forward Client → Deepgram
        while not stop_event.is_set():
            try:
                # Receive from client (with timeout to check stop_event)
                data = ws.receive(timeout=1.0)

                if data is None:
                    # Timeout or connection closed
                    if stop_event.is_set():
                        break
                    continue

                # Forward to Deepgram (preserves binary/text)
                if isinstance(data, bytes):
                    deepgram_ws.send_binary(data)
                else:
                    deepgram_ws.send(data)

            except Exception as e:
                if not stop_event.is_set():
                    print(f'Error in client receive loop: {e}')
                break

    except websocket.WebSocketException as e:
        print(f'Deepgram WebSocket error: {e}')
        try:
            ws.send(json.dumps({
                'type': 'Error',
                'description': str(e),
                'code': 'PROVIDER_ERROR'
            }))
        except:
            pass
    except Exception as e:
        print(f'Error in WebSocket handler: {e}')
        try:
            ws.send(json.dumps({
                'type': 'Error',
                'description': 'Failed to establish proxy connection',
                'code': 'CONNECTION_FAILED'
            }))
        except:
            pass
    finally:
        # Cleanup
        print('Cleaning up connection...')
        stop_event.set()

        # Close Deepgram connection
        if deepgram_ws:
            try:
                deepgram_ws.close()
            except Exception as e:
                print(f'Error closing Deepgram connection: {e}')

        print('Connection cleanup complete')

# ============================================================================
# SERVER START
# ============================================================================

if __name__ == '__main__':
    port = CONFIG['port']
    host = CONFIG['host']
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'

    nonce_status = " (nonce required)" if REQUIRE_NONCE else ""
    print('\n' + '=' * 70)
    print(f"🚀 Flask Voice Agent Server")
    print('=' * 70)
    print(f"Listening on http://{host}:{port}")
    print("")
    print(f"📡 GET  /api/session{nonce_status}")
    print("📡 WS   /api/voice-agent (auth required)")
    print("📡 GET  /api/metadata")
    print("")
    print(f"Debug:    {'ON' if debug else 'OFF'}")
    print('=' * 70 + '\n')

    # Run Flask app
    app.run(
        host=host,
        port=port,
        debug=debug
    )
