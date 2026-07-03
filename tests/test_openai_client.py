import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.openai_client import (
    OpenAIConfigurationError,
    OpenAIFileError,
    create_response,
    file_content_block,
)


class OpenAIClientTests(unittest.TestCase):
    def test_pdf_is_encoded_as_input_file(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as file_handle:
            file_handle.write(b"%PDF-1.4 test")
            path = Path(file_handle.name)
        try:
            block = file_content_block(path)
            self.assertEqual(block["type"], "input_file")
            self.assertEqual(block["filename"], path.name)
            self.assertTrue(block["file_data"].startswith("data:application/pdf;base64,"))
        finally:
            path.unlink(missing_ok=True)

    def test_empty_file_is_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as file_handle:
            path = Path(file_handle.name)
        try:
            with self.assertRaises(OpenAIFileError):
                file_content_block(path)
        finally:
            path.unlink(missing_ok=True)

    def test_authentication_error_is_actionable(self):
        class AuthenticationError(Exception):
            status_code = 401
            request_id = "test-request"

        class Responses:
            def create(self, **kwargs):
                raise AuthenticationError("invalid key")

        class Client:
            responses = Responses()

        with patch("app.services.openai_client.get_client", return_value=Client()):
            with self.assertRaisesRegex(
                OpenAIConfigurationError, "rejected the API key"
            ):
                create_response(prompt="test")


if __name__ == "__main__":
    unittest.main()
