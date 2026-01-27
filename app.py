"""
Flask Voice Agent Starter - Backend Server

Simple WebSocket proxy to Deepgram's Voice Agent API.
Forwards all messages (JSON and binary) bidirectionally between client and Deepgram.
"""

import os
import json
import threading
from flask import Flask, jsonify, send_from_directory, request
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
    'port': int(os.environ.get('PORT', 8080)),
    'host': os.environ.get('HOST', '0.0.0.0'),
    'vite_port': int(os.environ.get('VITE_PORT', 5173)),
    'is_development': os.environ.get('FLASK_ENV') == 'development',
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
# SETUP - Initialize Flask, WebSocket, and CORS
# ============================================================================

# Initialize Flask app
app = Flask(__name__, static_folder="./frontend/dist", static_url_path="/")

# Enable CORS for development
CORS(app, resources={
    r"/*": {
        "origins": "*",  # In production, restrict to your domain
        "allow_headers": ["Content-Type"],
        "supports_credentials": True
    }
})

# Initialize native WebSocket support
sock = Sock(app)

# ============================================================================
# API ROUTES
# ============================================================================

@app.route('/metadata')
def metadata():
    """Returns info from deepgram.toml"""
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
# FRONTEND SERVING (Development vs Production Pattern)
# ============================================================================
#
# This pattern allows framework-agnostic frontend/backend integration:
#
# DEVELOPMENT MODE (FLASK_ENV=development):
#   - Vite dev server runs independently on port 5173 (or VITE_PORT)
#   - Backend proxies ALL requests to Vite for HMR and fast refresh
#   - Vite proxies API routes (/agent, /metadata) back to backend
#   - User accesses: http://localhost:8080
#   - Flow: User → :8080 (Backend) → :5173 (Vite) → [API requests back to :8080]
#
# PRODUCTION MODE (FLASK_ENV=production or default):
#   - Frontend is pre-built (make build) to frontend/dist
#   - Backend serves static files directly from frontend/dist
#   - Backend handles API routes directly
#   - User accesses: http://localhost:8080
#   - Flow: User → :8080 (Backend serves static + APIs)
#
# ============================================================================

if CONFIG['is_development']:
    print(f"Development mode: Proxying to Vite dev server on port {CONFIG['vite_port']}")

    import requests

    @app.route('/')
    @app.route('/<path:path>')
    def proxy_to_vite(path=''):
        """Proxy all non-API/WebSocket requests to Vite dev server"""
        # Don't proxy API or WebSocket routes - they're handled elsewhere
        if path.startswith('metadata') or path.startswith('agent'):
            # Return 404 - these paths should be handled by other routes
            return '', 404

        # Proxy to Vite
        vite_url = f"http://localhost:{CONFIG['vite_port']}/{path}"
        try:
            resp = requests.get(vite_url, stream=True, headers=dict(request.headers))
            return resp.content, resp.status_code, dict(resp.headers)
        except requests.exceptions.RequestException as e:
            print(f"Error proxying to Vite: {e}")
            return f"Error: Cannot connect to Vite dev server on port {CONFIG['vite_port']}", 502
else:
    print('Production mode: Serving static files from frontend/dist')

    @app.route('/')
    @app.route('/<path:path>')
    def serve_static(path=''):
        """Serve static files from frontend/dist"""
        if path and os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        return send_from_directory(app.static_folder, 'index.html')

# ============================================================================
# WEBSOCKET ENDPOINT - Voice Agent (Simple Pass-Through Proxy)
# ============================================================================

@sock.route('/agent/converse')
def voice_agent(ws):
    """
    WebSocket endpoint for voice agent conversations
    Simple pass-through proxy - forwards all messages bidirectionally
    """
    print('Client connected to /agent/converse')

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
    print(f"Flask Voice Agent Server running at http://localhost:{port}")
    print(f"WebSocket endpoint: ws://localhost:{port}/agent/converse")
    print(f"Metadata endpoint: http://localhost:{port}/metadata")
    if CONFIG['is_development']:
        print(f"Make sure Vite dev server is running on port {CONFIG['vite_port']}")
        print(f"\n⚠️  Open your browser to http://localhost:{port}")
    print('=' * 70 + '\n')

    # Run Flask app
    app.run(
        host=host,
        port=port,
        debug=debug
    )
