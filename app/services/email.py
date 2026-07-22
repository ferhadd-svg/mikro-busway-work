"""
Send a generated quotation by email over SMTP.

Kept as a thin service (same separation as apply_outcome in
app.services.projects) so the router stays thin and this is unit-testable
by monkeypatching smtplib.SMTP. SMTP is the only transport for now; if a
transactional-email API is added later, only this module changes.
"""

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from app.config import settings

_XLSX_SUBTYPE = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def email_configured() -> bool:
    """True only when enough SMTP config exists to attempt a send."""
    return bool(settings.smtp_host and settings.smtp_user)


def send_quotation_email(
    to: list[str],
    cc: list[str],
    subject: str,
    body: str,
    attachment: Path,
) -> None:
    """Compose and send the quotation email with the .xlsx attached.
    Raises RuntimeError if email isn't configured; lets smtplib exceptions
    propagate so the router can surface a send failure distinctly."""
    if not email_configured():
        raise RuntimeError(
            "Email is not configured. Set SMTP_HOST / SMTP_USER / SMTP_PASSWORD."
        )

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(body)

    msg.add_attachment(
        attachment.read_bytes(),
        maintype="application",
        subtype=_XLSX_SUBTYPE,
        filename=attachment.name,
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_use_tls:
            server.starttls(context=ssl.create_default_context())
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)  # send_message routes To + Cc automatically
