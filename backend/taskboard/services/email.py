"""Outbound email. `smtp` delivers via the configured SMTP server; `console`
writes the message to the structured log (for local/dev deployments without SMTP)."""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from taskboard.config import get_settings
from taskboard.logging import get_logger

log = get_logger(__name__)


async def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if s.email_backend == "console":
        log.info("email_console_delivery", to=to, subject=subject, body=body)
        return
    msg = EmailMessage()
    msg["From"] = s.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        await aiosmtplib.send(
            msg,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_username or None,
            password=s.smtp_password.get_secret_value() or None,
            start_tls=s.smtp_starttls and not s.smtp_use_tls,
            use_tls=s.smtp_use_tls,
            timeout=15,
        )
        log.info("email_sent", to=to, subject=subject)
    except Exception:
        # Never leak delivery failures to the requester (avoids account enumeration);
        # operators see the failure in logs.
        log.exception("email_send_failed", to=to, subject=subject)
