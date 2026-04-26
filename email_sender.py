"""Gmail SMTP sender for the Daily News Brief.

Uses the user's Gmail account with an App Password (NOT the account password).
The brief is sent as both the inline HTML body AND as a .html attachment, in
one multipart/mixed message. Multiple recipients are supported.

Required env:
  GMAIL_USER          full Gmail address that does the sending
  GMAIL_APP_PASSWORD  16-char App Password from
                      https://myaccount.google.com/apppasswords
  RECIPIENT_EMAIL     comma-separated list of recipients
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Iterable


def _required(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"{name} is not set in the environment.")
    return val


def _recipients() -> list[str]:
    raw = _required("RECIPIENT_EMAIL")
    return [r.strip() for r in raw.split(",") if r.strip()]


def send_brief(
    *,
    html: str,
    subject: str,
    attachment_filename: str,
    text_preface: str,
    recipients: Iterable[str] | None = None,
) -> None:
    """Send the daily brief. Raises on failure (so launchd captures it)."""
    user = _required("GMAIL_USER")
    pwd = _required("GMAIL_APP_PASSWORD")
    rcpts = list(recipients) if recipients else _recipients()

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = ", ".join(rcpts)
    msg["Subject"] = subject
    # Plain-text fallback (very few clients will actually show this).
    msg.set_content(
        text_preface
        + "\n\n(This message contains HTML and an attached .html file. "
        "Open the attachment for the full brief if your client doesn't render HTML.)"
    )
    # Inline HTML so Gmail web/mobile renders the brief in the body too.
    msg.add_alternative(html, subtype="html")
    # And attach the same HTML as a downloadable file.
    msg.add_attachment(
        html.encode("utf-8"),
        maintype="text",
        subtype="html",
        filename=attachment_filename,
    )

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(user, pwd)
        smtp.send_message(msg, from_addr=user, to_addrs=rcpts)
