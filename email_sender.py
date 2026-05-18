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
import time
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


# Errors worth retrying — transient network / SMTP-side issues. We intentionally
# do NOT retry SMTPAuthenticationError (revoked App Password — needs human fix)
# or SMTPRecipientsRefused (bad address — needs human fix).
_RETRYABLE_SMTP_ERRORS = (
    smtplib.SMTPConnectError,
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPHeloError,
    smtplib.SMTPDataError,
    ConnectionResetError,
    ConnectionAbortedError,
    TimeoutError,
    OSError,
)


def send_brief(
    *,
    html: str,
    subject: str,
    attachment_filename: str,
    text_preface: str,
    recipients: Iterable[str] | None = None,
    max_attempts: int = 5,
) -> None:
    """Send the daily brief, retrying transient SMTP/network errors.

    Retries up to `max_attempts` times with exponential backoff
    (15s, 30s, 60s, 120s). Auth failures and bad-recipient errors
    raise immediately because they need human intervention — no
    amount of retrying fixes a revoked Gmail App Password.
    """
    user = _required("GMAIL_USER")
    pwd = _required("GMAIL_APP_PASSWORD")
    rcpts = list(recipients) if recipients else _recipients()

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = ", ".join(rcpts)
    msg["Subject"] = subject
    msg.set_content(
        text_preface
        + "\n\n(This message contains HTML and an attached .html file. "
        "Open the attachment for the full brief if your client doesn't render HTML.)"
    )
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(
        html.encode("utf-8"),
        maintype="text",
        subtype="html",
        filename=attachment_filename,
    )

    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(user, pwd)
                smtp.send_message(msg, from_addr=user, to_addrs=rcpts)
            if attempt > 1:
                print(f"[send] succeeded on attempt {attempt}", flush=True)
            return
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused):
            # Permanent — re-raise so the operator sees it (App Password revoked etc).
            raise
        except _RETRYABLE_SMTP_ERRORS as exc:
            last_err = exc
            if attempt == max_attempts:
                break
            delay = 15 * (2 ** (attempt - 1))  # 15, 30, 60, 120 seconds
            print(
                f"[send] attempt {attempt}/{max_attempts} failed "
                f"({type(exc).__name__}: {exc}); retrying in {delay}s",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(
        f"send_brief failed after {max_attempts} attempts; last error: {last_err}"
    )
