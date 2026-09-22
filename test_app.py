import json
import inspect
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DEEPGRAM_API_KEY", "test-api-key")

from app import (
    app,
    _connection_request_id,
    _forward_to_browser,
    _load_socket_client_class,
    _require_raw_sender,
    _safe_error_detail,
    V1SocketClient,
)
from deepgram.core.api_error import ApiError
from simple_websocket import ConnectionClosed
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response


class SafeErrorDetailTests(unittest.TestCase):
    def test_api_error_does_not_expose_authorization_header(self):
        detail = _safe_error_detail(
            ApiError(
                status_code=401,
                headers={"Authorization": "Token FAKE"},
                body="invalid credentials",
            )
        )

        self.assertIn("HTTP 401", detail)
        self.assertNotIn("FAKE", detail)

    def test_rejected_websocket_handshake_keeps_its_status(self):
        detail = _safe_error_detail(
            InvalidStatus(Response(401, "Unauthorized", Headers()))
        )

        self.assertEqual(detail, "Deepgram rejected the connection (HTTP 401)")

    def test_connection_errors_are_not_reported_as_failed_connections(self):
        self.assertEqual(
            _safe_error_detail(RuntimeError()),
            "Deepgram connection error (RuntimeError)",
        )

    def test_connection_error_forwards_sanitized_detail_to_browser(self):
        class Browser:
            def __init__(self):
                self.messages = []

            def send(self, message):
                self.messages.append(message)

        class FailedConnection:
            def __enter__(self):
                raise ApiError(
                    status_code=401,
                    headers={"Authorization": "Token FAKE"},
                    body="invalid credentials",
                )

            def __exit__(self, *_):
                return False

        browser = Browser()
        with (
            patch("app.validate_ws_token", return_value="access_token.test"),
            patch("app.deepgram.agent.v1.connect", return_value=FailedConnection()),
        ):
            app.view_functions["voice_agent"].__wrapped__(browser)

        error = json.loads(browser.messages[0])
        self.assertEqual(
            error["description"],
            "Deepgram rejected the connection (HTTP 401)",
        )
        self.assertNotIn("FAKE", browser.messages[0])


class SdkCompatibilityTests(unittest.TestCase):
    def test_sdk_raw_sender_accepts_one_control_payload(self):
        parameters = list(inspect.signature(V1SocketClient._send).parameters.values())
        self.assertEqual(len(parameters), 2)
        self.assertEqual(parameters[1].default, inspect.Parameter.empty)

    def test_missing_raw_sender_stops_startup(self):
        with self.assertRaisesRegex(SystemExit, "V1SocketClient._send"):
            _require_raw_sender(object)

    def test_missing_socket_client_module_stops_startup(self):
        with patch("builtins.__import__", side_effect=ModuleNotFoundError):
            with self.assertRaisesRegex(SystemExit, "last 7.x release"):
                _load_socket_client_class()


class VoiceAgentCloseTests(unittest.TestCase):
    def test_clean_deepgram_close_is_not_logged_as_an_error(self):
        class NormalClose(Exception):
            pass

        class Browser:
            def receive(self, timeout):
                return '{"type":"KeepAlive"}'

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def on(self, *_):
                pass

            def start_listening(self):
                pass

            def _send(self, _):
                raise NormalClose()

        with (
            patch("app.ConnectionClosedOK", NormalClose),
            patch("app.validate_ws_token", return_value="access_token.test"),
            patch("app.deepgram.agent.v1.connect", return_value=Connection()),
            patch("builtins.print") as log,
        ):
            app.view_functions["voice_agent"].__wrapped__(Browser())

        self.assertFalse(
            any(
                args and "Error forwarding to Deepgram" in args[0]
                for args, _ in log.call_args_list
            )
        )


class MessageForwardingTests(unittest.TestCase):
    class Browser:
        def __init__(self):
            self.messages = []

        def send(self, message):
            self.messages.append(message)

    class PydanticV1Message:
        def json(self):
            return '{"type":"Welcome","extra":"preserved"}'

    def test_pydantic_v1_messages_use_json(self):
        browser = self.Browser()

        self.assertTrue(_forward_to_browser(browser, self.PydanticV1Message()))
        self.assertEqual(browser.messages, ['{"type":"Welcome","extra":"preserved"}'])

    def test_browser_disconnect_stops_forwarding_without_raising(self):
        class DisconnectedBrowser:
            def send(self, _):
                raise ConnectionClosed(1000, "closed")

        self.assertFalse(_forward_to_browser(DisconnectedBrowser(), {"type": "Welcome"}))


class ConnectionRequestIdTests(unittest.TestCase):
    def test_missing_private_transport_only_omits_request_id(self):
        self.assertIsNone(_connection_request_id(object()))

    def test_reads_request_id_when_sdk_transport_exposes_it(self):
        response = type("Response", (), {"headers": {"dg-request-id": "request-123"}})()
        websocket = type("WebSocket", (), {"response": response})()
        connection = type(
            "Connection",
            (),
            {"_websocket": websocket},
        )()

        self.assertEqual(_connection_request_id(connection), "request-123")


if __name__ == "__main__":
    unittest.main()
