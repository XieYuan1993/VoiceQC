"""Outbound email (password reset). MailHog in dev, real relay in prod.

smtplib is blocking — callers run this via fastapi.concurrency.run_in_threadpool.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.settings import settings


def send_password_reset(to_email: str, reset_url: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = "VoiceQA — password reset"
    msg["From"] = settings.MAIL_FROM
    msg["To"] = to_email
    msg.set_content(
        "A password reset was requested for your VoiceQA account.\n\n"
        f"Reset your password (link expires in 30 minutes):\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        if settings.SMTP_USER:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS.get_secret_value())
        smtp.send_message(msg)
