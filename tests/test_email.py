import smtplib

import pytest

from app.config import settings
from app.services import email as email_service


class _FakeSMTP:
    """Records everything the sender does, so tests can assert without a
    real network connection. Mirrors the context-manager + method surface
    send_quotation_email() uses."""
    last_instance = None

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tls_started = False
        self.login_args = None
        self.sent_message = None
        _FakeSMTP.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.tls_started = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        self.sent_message = msg


@pytest.fixture
def smtp_settings(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_user", "sender@itmikro.com")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(settings, "smtp_from", "")
    monkeypatch.setattr(settings, "smtp_use_tls", True)
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)


def _attachment(tmp_path):
    f = tmp_path / "QUOTATION_MK-1.xlsx"
    f.write_bytes(b"fake-xlsx-bytes")
    return f


def test_email_configured_false_when_host_empty(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_user", "x@y.com")
    assert email_service.email_configured() is False


def test_email_configured_true_when_host_and_user_set(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "x@y.com")
    assert email_service.email_configured() is True


def test_send_raises_when_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "smtp_host", "")
    with pytest.raises(RuntimeError):
        email_service.send_quotation_email(
            ["c@client.com"], [], "Subj", "Body", _attachment(tmp_path)
        )


def test_send_composes_message_and_attaches_file(smtp_settings, tmp_path):
    email_service.send_quotation_email(
        to=["client@acme.com", "buyer@acme.com"],
        cc=["sales@itmikro.com"],
        subject="Quotation MK/1",
        body="Please find attached.",
        attachment=_attachment(tmp_path),
    )
    smtp = _FakeSMTP.last_instance
    assert smtp.tls_started is True
    assert smtp.login_args == ("sender@itmikro.com", "secret")

    msg = smtp.sent_message
    assert msg["From"] == "sender@itmikro.com"       # smtp_from blank -> falls back to user
    assert msg["To"] == "client@acme.com, buyer@acme.com"
    assert msg["Cc"] == "sales@itmikro.com"
    assert msg["Subject"] == "Quotation MK/1"

    attachments = [p for p in msg.iter_attachments()]
    assert len(attachments) == 1
    part = attachments[0]
    assert part.get_filename() == "QUOTATION_MK-1.xlsx"
    assert part.get_content_type() == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert part.get_payload(decode=True) == b"fake-xlsx-bytes"


def test_send_uses_smtp_from_when_set(smtp_settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "smtp_from", "quotes@itmikro.com")
    email_service.send_quotation_email(
        ["client@acme.com"], [], "Subj", "Body", _attachment(tmp_path)
    )
    assert _FakeSMTP.last_instance.sent_message["From"] == "quotes@itmikro.com"
