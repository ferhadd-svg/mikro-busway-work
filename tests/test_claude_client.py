import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.services.claude_client import (
    ClaudeConfigurationError,
    ClaudeFileError,
    create_message,
    file_content_block,
)


class ClaudeClientTests(unittest.TestCase):
    def test_pdf_is_encoded_as_document(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as file_handle:
            file_handle.write(b"%PDF-1.4 test")
            path = Path(file_handle.name)
        try:
            block = file_content_block(path)
            self.assertEqual(block["type"], "document")
            self.assertEqual(block["source"]["media_type"], "application/pdf")
        finally:
            path.unlink(missing_ok=True)

    def test_empty_file_is_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as file_handle:
            path = Path(file_handle.name)
        try:
            with self.assertRaises(ClaudeFileError):
                file_content_block(path)
        finally:
            path.unlink(missing_ok=True)

    def test_authentication_error_is_actionable(self):
        class AuthenticationError(Exception):
            status_code = 401
            request_id = "test-request"

        class Messages:
            def create(self, **kwargs):
                raise AuthenticationError("invalid key")

        class Client:
            messages = Messages()

        with patch("app.services.claude_client.get_client", return_value=Client()):
            with self.assertRaisesRegex(
                ClaudeConfigurationError, "rejected the API key"
            ):
                create_message(prompt="test")


if __name__ == "__main__":
    unittest.main()
