import os
import unittest

os.environ.setdefault("DEEPGRAM_API_KEY", "test-api-key")

from app import (
    _connection_request_id,
    _forward_to_browser,
    _require_raw_sender,
    _safe_error_detail,
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


class SdkCompatibilityTests(unittest.TestCase):
    def test_missing_raw_sender_stops_startup(self):
        with self.assertRaisesRegex(SystemExit, "V1SocketClient._send"):
            _require_raw_sender(object)


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
