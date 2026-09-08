import os
import unittest

os.environ.setdefault("DEEPGRAM_API_KEY", "test-api-key")

from app import _safe_error_detail
from deepgram.core.api_error import ApiError
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


if __name__ == "__main__":
    unittest.main()
