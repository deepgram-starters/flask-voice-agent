"""
Flask Voice Agent Starter - Backend Server

This Flask server provides a WebSocket endpoint for voice agent conversations
powered by Deepgram's Voice Agent service. It proxies to the Deepgram Agent API
and forwards all events between the frontend and Deepgram.

Key Features:
- WebSocket endpoint: /agent/converse
- Bidirectional audio and message streaming
- Forwards all agent events (Welcome, ConversationText, Audio, etc.)
- Serves built frontend from frontend/dist/
"""

import os
import json
import threading
from flask import Flask
from flask_sock import Sock
from flask_cors import CORS
from deepgram import DeepgramClient
from dotenv import load_dotenv

# Load .env file (won't override existing environment variables)
load_dotenv(override=False)

# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_PORT = 8080

# ============================================================================
# API KEY VALIDATION
# ============================================================================

def validate_api_key():
    """Validates that the Deepgram API key is configured"""
    api_key = os.environ.get("DEEPGRAM_API_KEY")

    if not api_key:
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
        raise ValueError("DEEPGRAM_API_KEY environment variable is required")

    return api_key

# Validate on startup
API_KEY = validate_api_key()

# ============================================================================
# SETUP - Initialize Flask, WebSocket, and CORS
# ============================================================================

# Initialize Flask app - serve built frontend from frontend/dist/
app = Flask(__name__, static_folder="./frontend/dist", static_url_path="/")

# Enable CORS for development (allows Vite dev server to connect)
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
# HTTP ROUTES
# ============================================================================

@app.route("/")
def index():
    """Serve the main frontend HTML file"""
    return app.send_static_file("index.html")

# ============================================================================
# WEBSOCKET ENDPOINT - Voice Agent
# ============================================================================

@sock.route('/agent/converse')
def voice_agent(ws):
    """
    WebSocket endpoint for voice agent conversations

    The client sends:
    - Binary data: audio frames
    - JSON messages: Settings, InjectUserMessage, and other control messages

    The server sends:
    - Binary data: audio frames from the agent
    - JSON messages: Welcome, SettingsApplied, ConversationText, AgentThinking,
                    UserStartedSpeaking, AgentAudioDone, Error, Warning, etc.
    """
    print("Client connected to /agent/converse")

    # Thread control
    stop_event = threading.Event()
    deepgram_agent = None
    deepgram_context = None

    try:
        # Validate API key
        if not API_KEY:
            error_msg = {
                'type': 'Error',
                'description': 'Missing Deepgram API key',
                'code': 'MISSING_API_KEY'
            }
            ws.send(json.dumps(error_msg))
            return

        # Initialize Deepgram client
        client = DeepgramClient(api_key=API_KEY)

        # Create agent connection
        deepgram_context = client.agent.websocket.v("1")
        deepgram_agent = deepgram_context

        # Set up Deepgram event handlers
        def on_open(self, open_event, **kwargs):
            """Handle Deepgram connection open"""
            print("Deepgram agent connection opened")

        def on_welcome(self, welcome, **kwargs):
            """Forward Welcome message to client"""
            if welcome:
                ws.send(json.dumps(welcome.__dict__))

        def on_settings_applied(self, settings_applied, **kwargs):
            """Forward SettingsApplied message to client"""
            if settings_applied:
                ws.send(json.dumps(settings_applied.__dict__))

        def on_conversation_text(self, conversation_text, **kwargs):
            """Forward ConversationText events to client"""
            if conversation_text:
                ws.send(json.dumps(conversation_text.__dict__))

        def on_user_started_speaking(self, user_started_speaking, **kwargs):
            """Forward UserStartedSpeaking events to client"""
            if user_started_speaking:
                ws.send(json.dumps(user_started_speaking.__dict__))

        def on_agent_thinking(self, agent_thinking, **kwargs):
            """Forward AgentThinking events to client"""
            if agent_thinking:
                ws.send(json.dumps(agent_thinking.__dict__))

        def on_agent_audio_done(self, agent_audio_done, **kwargs):
            """Forward AgentAudioDone events to client"""
            if agent_audio_done:
                ws.send(json.dumps(agent_audio_done.__dict__))

        def on_audio(self, audio_data, **kwargs):
            """Forward audio chunks to client"""
            if audio_data:
                # Send as binary data
                ws.send(audio_data)

        def on_error(self, error, **kwargs):
            """Forward Error events to client"""
            print(f"Deepgram agent error: {error}")

            # Map Deepgram errors to error codes
            error_code = 'PROVIDER_ERROR'
            error_msg = str(error) if error else 'Unknown error occurred'

            if error_msg and 'auth' in error_msg.lower():
                error_code = 'MISSING_API_KEY'
            elif error_msg and 'audio' in error_msg.lower():
                error_code = 'AUDIO_FORMAT_ERROR'

            error_response = {
                'type': 'Error',
                'description': error_msg,
                'code': error_code
            }
            ws.send(json.dumps(error_response))

        def on_warning(self, warning, **kwargs):
            """Forward Warning events to client"""
            if warning:
                ws.send(json.dumps(warning.__dict__))

        def on_injection_refused(self, injection_refused, **kwargs):
            """Forward InjectionRefused events to client"""
            if injection_refused:
                ws.send(json.dumps(injection_refused.__dict__))

        def on_close(self, close_event, **kwargs):
            """Handle Deepgram connection close"""
            print("Deepgram agent connection closed")
            stop_event.set()

        # Register event handlers (using the Python SDK's event system)
        # Note: The exact event names may differ - adjust based on SDK version
        try:
            from deepgram import AgentWebSocketEvents
            deepgram_agent.on(AgentWebSocketEvents.Open, on_open)
            deepgram_agent.on(AgentWebSocketEvents.Welcome, on_welcome)
            deepgram_agent.on(AgentWebSocketEvents.SettingsApplied, on_settings_applied)
            deepgram_agent.on(AgentWebSocketEvents.ConversationText, on_conversation_text)
            deepgram_agent.on(AgentWebSocketEvents.UserStartedSpeaking, on_user_started_speaking)
            deepgram_agent.on(AgentWebSocketEvents.AgentThinking, on_agent_thinking)
            deepgram_agent.on(AgentWebSocketEvents.AgentAudioDone, on_agent_audio_done)
            deepgram_agent.on(AgentWebSocketEvents.Audio, on_audio)
            deepgram_agent.on(AgentWebSocketEvents.Error, on_error)
            deepgram_agent.on(AgentWebSocketEvents.Warning, on_warning)
            deepgram_agent.on(AgentWebSocketEvents.InjectionRefused, on_injection_refused)
            deepgram_agent.on(AgentWebSocketEvents.Close, on_close)
        except ImportError:
            # Fallback for older SDK versions
            print("Warning: Could not import AgentWebSocketEvents. Using fallback event registration.")

        # Start the Deepgram agent connection
        # Note: start() signature may vary by SDK version
        if not deepgram_agent.start():
            print("Failed to start Deepgram agent connection")
            error_response = {
                'type': 'Error',
                'description': 'Failed to initialize agent connection',
                'code': 'CONNECTION_FAILED'
            }
            ws.send(json.dumps(error_response))
            return

        print("Deepgram agent connection started, waiting for messages...")

        # Main loop: receive messages from client and forward to Deepgram
        while not stop_event.is_set():
            try:
                data = ws.receive(timeout=1)  # 1 second timeout to check stop_event

                if data is None:
                    # Connection closed or timeout
                    if stop_event.is_set():
                        break
                    continue

                if isinstance(data, bytes):
                    # Binary audio data - validate and forward to Deepgram
                    if not data or len(data) == 0:
                        error_response = {
                            'type': 'Error',
                            'description': 'Invalid audio data: empty buffer',
                            'code': 'AUDIO_FORMAT_ERROR'
                        }
                        ws.send(json.dumps(error_response))
                        continue

                    # Forward audio to Deepgram
                    deepgram_agent.send_audio(data)

                elif isinstance(data, str):
                    # JSON message - parse and handle
                    try:
                        message = json.loads(data)
                        message_type = message.get('type')

                        if message_type == 'Settings':
                            # Validate Settings message
                            if not message.get('audio') or not message.get('agent'):
                                error_response = {
                                    'type': 'Error',
                                    'description': 'Invalid Settings message: missing required fields',
                                    'code': 'INVALID_SETTINGS'
                                }
                                ws.send(json.dumps(error_response))
                                continue

                            # Validate audio configuration
                            audio = message.get('audio', {})
                            if not audio.get('input') or not audio.get('output'):
                                error_response = {
                                    'type': 'Error',
                                    'description': 'Invalid Settings message: missing audio configuration',
                                    'code': 'AUDIO_FORMAT_ERROR'
                                }
                                ws.send(json.dumps(error_response))
                                continue

                            # Validate audio encoding
                            valid_encodings = ['linear16', 'linear32', 'mulaw']
                            input_encoding = audio.get('input', {}).get('encoding')
                            output_encoding = audio.get('output', {}).get('encoding')

                            if (input_encoding not in valid_encodings or
                                output_encoding not in valid_encodings):
                                error_response = {
                                    'type': 'Error',
                                    'description': 'Invalid audio encoding format',
                                    'code': 'AUDIO_FORMAT_ERROR'
                                }
                                ws.send(json.dumps(error_response))
                                continue

                            # Validate agent configuration
                            agent = message.get('agent', {})
                            if (not agent.get('listen') or
                                not agent.get('think') or
                                not agent.get('speak')):
                                error_response = {
                                    'type': 'Error',
                                    'description': 'Invalid Settings message: missing agent configuration',
                                    'code': 'INVALID_SETTINGS'
                                }
                                ws.send(json.dumps(error_response))
                                continue

                            # Convert to SettingsOptions and configure agent
                            from deepgram import SettingsOptions, Input, Output
                            options = SettingsOptions.from_json(json.dumps(message))

                            # Note: The SDK method name may vary - adjust as needed
                            if hasattr(deepgram_agent, 'configure'):
                                deepgram_agent.configure(options)
                            else:
                                # Fallback: send as raw message
                                deepgram_agent.send(json.dumps(message))

                        elif message_type == 'InjectUserMessage':
                            # Inject user message
                            content = message.get('content', '')
                            if hasattr(deepgram_agent, 'inject_user_message'):
                                deepgram_agent.inject_user_message(content)
                            else:
                                # Fallback: send as raw message
                                deepgram_agent.send(json.dumps(message))

                        else:
                            # Forward other JSON messages as-is
                            deepgram_agent.send(json.dumps(message))

                    except json.JSONDecodeError as e:
                        print(f"Invalid JSON received: {e}")
                        error_response = {
                            'type': 'Error',
                            'description': 'Invalid JSON format',
                            'code': 'CONNECTION_FAILED'
                        }
                        ws.send(json.dumps(error_response))

                    except Exception as e:
                        print(f"Error processing message: {e}")
                        error_response = {
                            'type': 'Error',
                            'description': str(e),
                            'code': 'CONNECTION_FAILED'
                        }
                        ws.send(json.dumps(error_response))

            except Exception as e:
                print(f"Error in receive loop: {e}")
                if not stop_event.is_set():
                    error_response = {
                        'type': 'Error',
                        'description': f'Error processing message: {str(e)}',
                        'code': 'CONNECTION_FAILED'
                    }
                    try:
                        ws.send(json.dumps(error_response))
                    except:
                        pass
                break

    except Exception as e:
        print(f"Error in WebSocket handler: {e}")
        try:
            error_response = {
                'type': 'Error',
                'description': 'Failed to initialize agent connection',
                'code': 'CONNECTION_FAILED'
            }
            ws.send(json.dumps(error_response))
        except:
            pass

    finally:
        # Cleanup
        print("Cleaning up connection...")
        stop_event.set()

        # Close Deepgram connection
        if deepgram_agent:
            try:
                deepgram_agent.finish()
            except Exception as e:
                print(f"Error finishing Deepgram connection: {e}")

        print("Connection cleanup complete")

# ============================================================================
# SERVER START
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    print("\n" + "=" * 70)
    print(f"🚀 Flask Voice Agent Server running at http://localhost:{port}")
    print(f"📦 Serving built frontend from frontend/dist")
    print(f"🔌 WebSocket endpoint: ws://localhost:{port}/agent/converse")
    print(f"🐞 Debug mode: {'ON' if debug else 'OFF'}")
    print("=" * 70 + "\n")

    # Run Flask app
    app.run(
        host=host,
        port=port,
        debug=debug
    )
