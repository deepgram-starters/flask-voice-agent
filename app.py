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
from flask import Flask, jsonify, request, send_from_directory
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
# SESSION AUTH - JWT tokens with rate limiting for production security
# ============================================================================

SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
JWT_EXPIRY = 3600  # 1 hour


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
    """Serve the built frontend index.html."""
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
    if not os.path.isfile(os.path.join(frontend_dir, "index.html")):
        return "Frontend not built. Run make build first.", 404
    return send_from_directory(frontend_dir, "index.html")


@app.route("/api/session", methods=["GET"])
def get_session():
    """Issues a JWT for session authentication."""
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

    print('\n' + '=' * 70)
    print(f"🚀 Flask Voice Agent Server")
    print('=' * 70)
    print(f"Listening on http://{host}:{port}")
    print("")
    print("📡 GET  /api/session")
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
