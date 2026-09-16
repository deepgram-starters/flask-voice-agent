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
from simple_websocket import ConnectionClosed, Server as _WsServer
import toml
from dotenv import load_dotenv
from websockets.exceptions import InvalidStatus

from deepgram import DeepgramClient
from deepgram.agent.v1.socket_client import V1SocketClient
from deepgram.core.events import EventType
from deepgram.core.api_error import ApiError

# Monkey-patch simple-websocket to echo back the access_token.* subprotocol.
# flask-sock uses simple-websocket's Server class for the WebSocket handshake.
# By default, Server.choose_subprotocol only accepts subprotocols that are in a
# static allow-list, which doesn't work for dynamic JWT-bearing subprotocols.
# This override makes the server echo back any access_token.* subprotocol so the
# client receives the Sec-WebSocket-Protocol response header it expects.
_original_choose_subprotocol = _WsServer.choose_subprotocol


def _choose_subprotocol_with_token(self, ws_request):
    for proto in ws_request.subprotocols:
        if proto.startswith("access_token."):
            return proto
    return _original_choose_subprotocol(self, ws_request)


_WsServer.choose_subprotocol = _choose_subprotocol_with_token

# Load .env file (won't override existing environment variables)
load_dotenv(override=False)

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    'deepgram_api_key': os.environ.get('DEEPGRAM_API_KEY'),
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


def _require_raw_sender(socket_client_class):
    """Fail fast when the SDK no longer supports raw control-frame forwarding."""
    if not callable(getattr(socket_client_class, "_send", None)):
        raise SystemExit(
            "deepgram-sdk no longer exposes V1SocketClient._send(); pin "
            "deepgram-sdk==7.8.1 or see "
            "https://github.com/deepgram/deepgram-python-sdk/issues/785"
        )


_require_raw_sender(V1SocketClient)

# One SDK client, reused across connections; the browser never sees the API key.
deepgram = DeepgramClient(api_key=CONFIG['deepgram_api_key'])


def _safe_error_detail(e):
    """Sanitize a Deepgram error before it reaches the browser or logs.

    NEVER surface str(e): a deepgram-sdk ApiError stringifies its request
    headers, which include Authorization: Token <api-key> — a bad connect
    would otherwise leak the key to the browser and the server logs.
    """
    if isinstance(e, ApiError):
        return f"Deepgram rejected the connection (HTTP {e.status_code})"
    if isinstance(e, InvalidStatus):
        return f"Deepgram rejected the connection (HTTP {e.response.status_code})"
    return f"Deepgram connection error ({type(e).__name__})"


def _forward_to_browser(ws, message):
    """Forward one Deepgram message to the browser: bytes as binary audio, models as JSON."""
    try:
        if isinstance(message, (bytes, bytearray)):
            ws.send(bytes(message))
        elif isinstance(message, dict):
            ws.send(json.dumps(message))
        elif hasattr(message, "json"):
            ws.send(message.json())
        else:
            ws.send(json.dumps({"type": getattr(message, "type", "Unknown")}))
        return True
    except Exception:
        return False


def _connection_request_id(connection):
    """Return the optional request ID without depending on SDK internals at runtime."""
    # The SDK has no public handshake-metadata API. Losing this optional support
    # identifier must not disrupt an otherwise healthy agent conversation.
    websocket = getattr(connection, "_websocket", None)
    response = getattr(websocket, "response", None)
    headers = getattr(response, "headers", None)
    return headers.get("dg-request-id") if headers else None

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

    stop_event = threading.Event()

    # Bridge browser <-> Deepgram Voice Agent through the official SDK (agent.v1).
    # This is a transparent proxy: the browser drives the full agent protocol
    # (it sends the Settings message and every control frame). Binary frames are
    # microphone audio; text frames are JSON control messages, forwarded verbatim.
    try:
        with deepgram.agent.v1.connect() as connection:
            def _on_deepgram_error(e):
                detail = _safe_error_detail(e)
                print(f"Deepgram error: {detail}")
                # Give the browser a structured Error frame before teardown so a
                # mid-session Deepgram error surfaces in the UI, matching the
                # pre-migration PROVIDER_ERROR contract (previously the browser
                # just saw the socket close with no payload).
                _forward_to_browser(ws, {
                    "type": "Error",
                    "description": detail,
                    "code": "PROVIDER_ERROR",
                })
                stop_event.set()

            def _on_deepgram_message(message):
                if not _forward_to_browser(ws, message):
                    stop_event.set()

            connection.on(EventType.MESSAGE, _on_deepgram_message)
            connection.on(EventType.CLOSE, lambda _: stop_event.set())
            connection.on(EventType.ERROR, _on_deepgram_error)

            # start_listening() blocks, so run it in a background thread while the
            # main thread forwards browser messages to Deepgram.
            threading.Thread(target=connection.start_listening, daemon=True).start()
            print('✓ Connected to Deepgram Agent API')
            request_id = _connection_request_id(connection)
            if request_id:
                print(f"Deepgram request ID: {request_id}")

            while not stop_event.is_set():
                try:
                    data = ws.receive(timeout=1.0)
                except ConnectionClosed:
                    break
                except Exception as e:
                    if not stop_event.is_set():
                        print(f'Error in client receive loop: {e}')
                    break
                if data is None:
                    continue

                try:
                    if isinstance(data, (bytes, bytearray)):
                        connection.send_media(bytes(data))
                    else:
                        # Forward the browser's JSON control frame (Settings, Update*,
                        # InjectAgentMessage, KeepAlive, ...) to Deepgram verbatim.
                        #
                        # NOTE: agent.v1 exposes only *typed* senders (send_settings,
                        # send_update_prompt, ...) and no public raw/dict send, so a
                        # transparent proxy has to use the private _send() here. This
                        # relies on a private, non-semver-stable method; it works
                        # because it is bounded to <8, not pinned. Tracking a public sender:
                        # https://github.com/deepgram/deepgram-python-sdk/issues/785
                        connection._send(data)
                except Exception as e:
                    print(f'Error forwarding to Deepgram: {_safe_error_detail(e)}')

    except Exception as e:
        print(f'Error in WebSocket handler: {_safe_error_detail(e)}')
        try:
            ws.send(json.dumps({
                'type': 'Error',
                'description': 'Failed to establish proxy connection',
                'code': 'CONNECTION_FAILED'
            }))
        except Exception:
            pass
    finally:
        # Cleanup
        print('Cleaning up connection...')
        stop_event.set()
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
