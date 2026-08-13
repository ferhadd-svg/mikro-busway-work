"""
Send a generated quotation by email via the Brevo transactional email API.

Kept as a thin service (same separation as apply_outcome in
app.services.projects) so the router stays thin and this is unit-testable
by monkeypatching urllib.request.urlopen. HTTPS is the only transport —
Render's free plan blocks all outbound traffic on SMTP ports 25/465/587,
so raw smtplib never works there regardless of correct credentials.
"""

import base64
import html
import json
import urllib.error
import urllib.request
from pathlib import Path

from app.config import settings

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

COMPANY_NAME = "MIKRO BUSWAY SDN BHD"
COMPANY_ADDRESS_LINES = [
    "No.61 & 62, Jalan Platinum 5/3,",
    "Pusat Perdagangan Nilai Impian XME,",
    "71800 Nilai, Negeri Sembilan.",
]
COMPANY_PHONE = "06-795 3362"


def _signature_text(name: str, title: str, mobile: str, email: str) -> str:
    lines = [
        "", "",
        name, title, f"Tel: {mobile}", f"Email: {email}",
        "",
        COMPANY_NAME,
        *COMPANY_ADDRESS_LINES,
        f"Tel: {COMPANY_PHONE}",
    ]
    return "\n".join(lines)


def _signature_html(name: str, title: str, mobile: str, email: str) -> str:
    logo_url = settings.public_base_url.rstrip("/") + "/static/mikro-logo.png"
    logo_img = (
        f'<img src="{logo_url}" alt="{COMPANY_NAME}" '
        f'style="height:48px;display:block;margin-bottom:8px;">'
    )
    address_html = "<br>".join(html.escape(line) for line in COMPANY_ADDRESS_LINES)
    return (
        '<div style="font-family:Arial,sans-serif;font-size:13px;color:#333;">'
        f"{logo_img}"
        f"<div><b>{html.escape(name)}</b></div>"
        f"<div>{html.escape(title)}</div>"
        f"<div>Tel: {html.escape(mobile)}</div>"
        f"<div>Email: {html.escape(email)}</div>"
        "<br>"
        f"<div><b>{COMPANY_NAME}</b></div>"
        f"<div>{address_html}</div>"
        f"<div>Tel: {COMPANY_PHONE}</div>"
        "</div>"
    )


def _api_key() -> str:
    return settings.brevo_api_key.strip()


def _sender_email() -> str:
    return settings.email_from.strip()


def email_configured() -> bool:
    """True only when enough config exists to attempt a send."""
    return bool(_api_key() and _sender_email())


def send_quotation_email(
    to: list[str],
    cc: list[str],
    subject: str,
    body: str,
    attachment: Path,
    sender_name: str | None = None,
    sender_title: str | None = None,
    sender_mobile: str | None = None,
    sender_email: str | None = None,
) -> None:
    """Compose and send the quotation email with the .xlsx attached.
    Raises RuntimeError if email isn't configured (the router maps this to a
    400 "not configured" response); raises ConnectionError if the API call
    itself fails (mapped to a 502 "send failed" response) — kept as a
    distinct type from RuntimeError so the router's except-clauses tell the
    two failure modes apart.

    When sender_* is given (the project's assigned salesperson), a signature
    with their name/title/mobile plus the company footer and logo is
    appended — same fields already used on the quotation document itself
    (see quotation_builder.build_quotation), so it stays in sync per person
    rather than being hardcoded to whoever wrote this code."""
    if not email_configured():
        raise RuntimeError(
            "Email is not configured. Set BREVO_API_KEY / EMAIL_FROM."
        )

    text_body = body
    html_body = None
    if sender_name:
        text_body = body + _signature_text(sender_name, sender_title or "", sender_mobile or "", sender_email or "")
        html_body = (
            f'<div style="font-family:Arial,sans-serif;font-size:14px;white-space:pre-wrap;">{html.escape(body)}</div>'
            "<br>"
            + _signature_html(sender_name, sender_title or "", sender_mobile or "", sender_email or "")
        )

    payload = {
        "sender": {"email": _sender_email()},
        "to": [{"email": addr} for addr in to],
        "subject": subject,
        "textContent": text_body,
        "attachment": [{
            "content": base64.b64encode(attachment.read_bytes()).decode(),
            "name": attachment.name,
        }],
    }
    if html_body:
        payload["htmlContent"] = html_body
    if cc:
        payload["cc"] = [{"email": addr} for addr in cc]

    request = urllib.request.Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "api-key": _api_key(),
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
