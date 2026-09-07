"""
Minimal SMTP email sending — works with any SMTP provider (Gmail app
password, Mailtrap for local dev testing, SendGrid SMTP relay, etc.).
No paid service required to get this running; just fill in the .env vars.

For local dev without a real inbox, Mailtrap (mailtrap.io) has a free
sandbox SMTP endpoint that catches emails in a web UI instead of actually
sending them — useful while testing this flow.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "no-reply@vendorpulse.app")

FRONTEND_RESET_URL = os.getenv("FRONTEND_RESET_URL", "http://localhost:8501/reset-password")


def send_email(to_email: str, subject: str, plain_text_body: str, html_body: str | None = None) -> None:
    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP is not configured — set SMTP_HOST, SMTP_USERNAME, "
            "SMTP_PASSWORD in your .env before calling send_email()."
        )

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = to_email

    message.attach(MIMEText(plain_text_body, "plain"))
    if html_body:
        message.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, to_email, message.as_string())


def send_password_reset_email(to_email: str, raw_token: str) -> None:
    reset_link = f"{FRONTEND_RESET_URL}?token={raw_token}"

    plain_text_body = (
        "We received a request to reset your VendorPulse password.\n\n"
        f"Reset link (valid for 30 minutes): {reset_link}\n\n"
        "If you didn't request this, you can safely ignore this email."
    )

    html_body = f"""
    <p>We received a request to reset your VendorPulse password.</p>
    <p><a href="{reset_link}">Click here to reset your password</a> (valid for 30 minutes).</p>
    <p>If you didn't request this, you can safely ignore this email.</p>
    """

    send_email(
        to_email=to_email,
        subject="Reset your VendorPulse password",
        plain_text_body=plain_text_body,
        html_body=html_body,
    )