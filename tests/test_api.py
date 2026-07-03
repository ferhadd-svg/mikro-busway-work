import unittest

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class ApiTests(unittest.TestCase):
    def test_health(self):
        with TestClient(app) as client:
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_ai_status_does_not_expose_key(self):
        with TestClient(app) as client:
            response = client.get("/ai/status")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("api_key", response.json())

    def test_missing_openai_key_returns_503(self):
        original_key = settings.openai_api_key
        settings.openai_api_key = ""
        try:
            with TestClient(app) as client:
                response = client.post("/ai/test-connection")
        finally:
            settings.openai_api_key = original_key
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
