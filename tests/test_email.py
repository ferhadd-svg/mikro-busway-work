import base64
import json
import urllib.error
import urllib.request

import pytest

from app.config import settings
from app.services import email as email_service


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """Records the last request urlopen() was called with, so tests can
    assert without a real network call. Set .raise_http/.raise_url to make
    the next call fail like a real Brevo error."""
    def __init__(self):
        self.last_request = None
        self.timeout = None
        self.raise_http = None
        self.raise_url = None

    def __call__(self, request, timeout=None):
        self.last_request = request
        self.timeout = timeout
        if self.raise_http:
            raise self.raise_http
        if self.raise_url:
            raise self.raise_url
        return _FakeResponse()


@pytest.fixture
def brevo_settings(monkeypatch):
    monkeypatch.setattr(settings, "brevo_api_key", "fake-api-key")
    monkeypatch.setattr(settings, "email_from", "sender@itmikro.com")
    fake = _FakeOpener()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def _attachment(tmp_path):
    f = tmp_path / "QUOTATION_MK-1.xlsx"
    f.write_bytes(b"fake-xlsx-bytes")
    return f


def _payload_of(request):
    return json.loads(request.data.decode())


def test_email_configured_false_when_api_key_empty(monkeypatch):
    monkeypatch.setattr(settings, "brevo_api_key", "")
    monkeypatch.setattr(settings, "email_from", "x@y.com")
    assert email_service.email_configured() is False


def test_email_configured_false_when_from_empty(monkeypatch):
    monkeypatch.setattr(settings, "brevo_api_key", "fake-key")
    monkeypatch.setattr(settings, "email_from", "")
    assert email_service.email_configured() is False


def test_email_configured_false_when_key_is_only_whitespace(monkeypatch):
    """A key that's just whitespace (e.g. an env var set to a single space
    by mistake) must not read as "configured" — .strip() would otherwise
    turn it into a legitimately-empty string that still passes a plain
    truthiness check on the unstripped value."""
    monkeypatch.setattr(settings, "brevo_api_key", "   \n")
    monkeypatch.setattr(settings, "email_from", "x@y.com")
    assert email_service.email_configured() is False


def test_email_configured_true_when_both_set(monkeypatch):
    monkeypatch.setattr(settings, "brevo_api_key", "fake-key")
    monkeypatch.setattr(settings, "email_from", "x@y.com")
    assert email_service.email_configured() is True


def test_send_raises_when_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "brevo_api_key", "")
    with pytest.raises(RuntimeError):
        email_service.send_quotation_email(
            ["c@client.com"], [], "Subj", "Body", _attachment(tmp_path)
        )


def test_send_posts_expected_payload_and_headers(brevo_settings, tmp_path):
    email_service.send_quotation_email(
        to=["client@acme.com", "buyer@acme.com"],
        cc=["sales@itmikro.com"],
        subject="Quotation MK/1",
        body="Please find attached.",
        attachment=_attachment(tmp_path),
    )
    req = brevo_settings.last_request
    assert req.full_url == email_service.BREVO_API_URL
    assert req.get_header("Api-key") == "fake-api-key"
    assert req.get_header("Content-type") == "application/json"

    payload = _payload_of(req)
    assert payload["sender"] == {"email": "sender@itmikro.com"}
    assert payload["to"] == [{"email": "client@acme.com"}, {"email": "buyer@acme.com"}]
    assert payload["cc"] == [{"email": "sales@itmikro.com"}]
    assert payload["subject"] == "Quotation MK/1"
    assert payload["textContent"] == "Please find attached."


def test_send_strips_whitespace_from_key_and_sender(brevo_settings, tmp_path, monkeypatch):
    """Real-world bug: a trailing newline/space from pasting the key into a
    web form's env-var field makes the transmitted header differ from the
    real key even though it looks identical — Brevo then reports "Key not
    found" for a key that is, to the human eye, correct. Confirmed live
    2026-08-13 with a freshly-generated key that still failed the same way."""
    monkeypatch.setattr(settings, "brevo_api_key", "  fake-api-key\n")
    monkeypatch.setattr(settings, "email_from", " sender@itmikro.com \t")
    email_service.send_quotation_email(
        ["client@acme.com"], [], "Subj", "Body", _attachment(tmp_path)
    )
    req = brevo_settings.last_request
    assert req.get_header("Api-key") == "fake-api-key"
    assert _payload_of(req)["sender"] == {"email": "sender@itmikro.com"}


def test_send_omits_cc_when_empty(brevo_settings, tmp_path):
    email_service.send_quotation_email(
        ["client@acme.com"], [], "Subj", "Body", _attachment(tmp_path)
    )
    payload = _payload_of(brevo_settings.last_request)
    assert "cc" not in payload


def test_send_wraps_http_error(brevo_settings, tmp_path):
    """A distinct type from RuntimeError — the router uses that distinction
    to tell "not configured" (400) apart from "send failed" (502)."""
    brevo_settings.raise_http = urllib.error.HTTPError(
        email_service.BREVO_API_URL, 401, "Unauthorized",
        hdrs=None, fp=__import__("io").BytesIO(b'{"message":"invalid api-key"}'),
    )
    with pytest.raises(ConnectionError, match="invalid api-key"):
        email_service.send_quotation_email(
            ["client@acme.com"], [], "Subj", "Body", _attachment(tmp_path)
        )


def test_send_wraps_url_error(brevo_settings, tmp_path):
    brevo_settings.raise_url = urllib.error.URLError("Network unreachable")
    with pytest.raises(ConnectionError, match="Network unreachable"):
        email_service.send_quotation_email(
            ["client@acme.com"], [], "Subj", "Body", _attachment(tmp_path)
        )
