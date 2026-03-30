"""Async email service using aiosmtplib (Gmail SMTP)."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger(__name__)


async def _send_email(smtp_config: dict[str, Any], to_email: str, subject: str, text_body: str, html_body: str) -> None:
    """Send an email via SMTP. No-ops if smtp_config has enabled=false."""
    if not smtp_config.get("enabled", True) is not False and smtp_config.get("enabled") is False:
        logger.info("SMTP disabled; skipping email to %s", to_email)
        return
    if smtp_config.get("enabled") is False:
        logger.info("SMTP disabled; skipping email to %s", to_email)
        return

    try:
        import aiosmtplib
    except ImportError:
        logger.warning("aiosmtplib not installed; skipping email to %s", to_email)
        return

    host = smtp_config.get("host", "smtp.gmail.com")
    port = int(smtp_config.get("port", 587))
    username = smtp_config.get("username", "")
    password = smtp_config.get("password", "")
    from_address = smtp_config.get("from_address", username)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=username,
            password=password,
            start_tls=True,
        )
        logger.info("Email sent to %s: %s", to_email, subject)
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, e)
        raise


async def send_verification_email(
    smtp_config: dict[str, Any],
    to_email: str,
    username: str,
    token: str,
    base_url: str,
) -> None:
    link = f"{base_url}/verify-email?token={token}"
    subject = "Verify your PaperIgnition email"
    text_body = f"""Hi {username},

Please verify your email address by clicking the link below:

{link}

This link expires in 24 hours.

If you didn't create a PaperIgnition account, you can safely ignore this email.

— The PaperIgnition Team
"""
    html_body = f"""<html><body style="font-family:sans-serif;color:#1a1a1a;max-width:480px;margin:0 auto;padding:24px">
<h2 style="color:#6366f1">Verify your email</h2>
<p>Hi <strong>{username}</strong>,</p>
<p>Click the button below to verify your email address.</p>
<p style="margin:32px 0">
  <a href="{link}" style="background:#6366f1;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600">
    Verify Email
  </a>
</p>
<p style="color:#6b7280;font-size:13px">Or copy this link: <a href="{link}">{link}</a></p>
<p style="color:#6b7280;font-size:13px">This link expires in 24 hours. If you didn't register, ignore this email.</p>
</body></html>"""
    await _send_email(smtp_config, to_email, subject, text_body, html_body)


async def send_password_reset_email(
    smtp_config: dict[str, Any],
    to_email: str,
    username: str,
    token: str,
    base_url: str,
) -> None:
    link = f"{base_url}/reset-password?token={token}"
    subject = "Reset your PaperIgnition password"
    text_body = f"""Hi {username},

We received a request to reset your password. Click the link below:

{link}

This link expires in 1 hour. If you didn't request this, you can safely ignore this email.

— The PaperIgnition Team
"""
    html_body = f"""<html><body style="font-family:sans-serif;color:#1a1a1a;max-width:480px;margin:0 auto;padding:24px">
<h2 style="color:#6366f1">Reset your password</h2>
<p>Hi <strong>{username}</strong>,</p>
<p>We received a request to reset your PaperIgnition password.</p>
<p style="margin:32px 0">
  <a href="{link}" style="background:#6366f1;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600">
    Reset Password
  </a>
</p>
<p style="color:#6b7280;font-size:13px">Or copy this link: <a href="{link}">{link}</a></p>
<p style="color:#6b7280;font-size:13px">This link expires in 1 hour. If you didn't request this, ignore this email.</p>
</body></html>"""
    await _send_email(smtp_config, to_email, subject, text_body, html_body)
