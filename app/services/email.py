"""
Send a generated quotation by email via the Brevo transactional email API.

Kept as a thin service (same separation as apply_outcome in
app.services.projects) so the router stays thin and this is unit-testable
by monkeypatching urllib.request.urlopen. HTTPS is the only transport —
Render's free plan blocks all outbound traffic on SMTP ports 25/465/587,
so raw smtplib never works there regardless of correct credentials.
"""

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

from app.config import settings

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def email_configured() -> bool:
    """True only when enough config exists to attempt a send."""
    return bool(settings.brevo_api_key and settings.email_from)


def send_quotation_email(
    to: list[str],
    cc: list[str],
    subject: str,
    body: str,
    attachment: Path,
) -> None:
    """Compose and send the quotation email with the .xlsx attached.
    Raises RuntimeError if email isn't configured (the router maps this to a
    400 "not configured" response); raises ConnectionError if the API call
    itself fails (mapped to a 502 "send failed" response) — kept as a
    distinct type from RuntimeError so the router's except-clauses tell the
    two failure modes apart."""
    if not email_configured():
        raise RuntimeError(
            "Email is not configured. Set BREVO_API_KEY / EMAIL_FROM."
        )

    payload = {
        "sender": {"email": settings.email_from},
        "to": [{"email": addr} for addr in to],
        "subject": subject,
        "textContent": body,
        "attachment": [{
            "content": base64.b64encode(attachment.read_bytes()).decode(),
            "name": attachment.name,
        }],
    }
    if cc:
        payload["cc"] = [{"email": addr} for addr in cc]

    request = urllib.request.Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "api-key": settings.brevo_api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30):
            pass
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise ConnectionError(f"Brevo send failed ({e.code}): {detail}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(f"Could not reach Brevo: {e.reason}") from e
