"""Where notifications go. Without SMTP settings they are written to data/outbox/ for preview, so nothing is
sent to anyone by accident during development."""

import hashlib
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from gooddaynews.notify.messages import Message
from gooddaynews.settings import ROOT


class OutboxSender:
    channel = "outbox"

    def __init__(self, folder: Path | None = None):
        self.folder = folder or ROOT / "data" / "outbox"

    def send(self, to: str, msg: Message, for_date) -> str:
        self.folder.mkdir(parents=True, exist_ok=True)
        # Hash the address so the outbox file names do not expose emails.
        name = f"{for_date}_{hashlib.sha256(to.encode()).hexdigest()[:10]}"
        (self.folder / f"{name}.html").write_text(
            f"<!-- To: {to} | Subject: {msg.subject} -->\n{msg.html}", encoding="utf-8")
        (self.folder / f"{name}.txt").write_text(f"Subject: {msg.subject}\n\n{msg.text}", encoding="utf-8")
        return str(self.folder / f"{name}.html")


class SmtpSender:
    channel = "email"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str):
        self.host, self.port, self.user, self.password, self.sender = host, port, user, password, sender

    def send(self, to: str, msg: Message, for_date) -> str:
        email = EmailMessage()
        email["Subject"], email["From"], email["To"] = msg.subject, self.sender, to
        email.set_content(msg.text)
        email.add_alternative(msg.html, subtype="html")
        with smtplib.SMTP_SSL(self.host, self.port, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(self.user, self.password)
            smtp.send_message(email)
        return "sent"


def get_sender():
    """SMTP when SMTP_HOST, SMTP_USER and SMTP_PASSWORD are set in .env; the local outbox otherwise."""
    host, user, password = os.getenv("SMTP_HOST"), os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
    if host and user and password:
        return SmtpSender(host, int(os.getenv("SMTP_PORT") or 465), user, password, os.getenv("SMTP_FROM") or user)
    return OutboxSender()
