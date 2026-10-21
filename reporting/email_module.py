"""Send email over SMTP with optional file attachments."""

import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable, Optional, Union

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")


def send_email(
    subject: str,
    body: str,
    recipients: Union[str, Iterable[str]],
    attachments: Optional[Iterable[str]] = None,
) -> bool:
    smtp_host = os.getenv("SMTP_SERVER") or os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_SENDER") or os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    sender_email = os.getenv("SMTP_SENDER") or os.getenv("REPORT_FROM_EMAIL") or smtp_username

    if not smtp_host:
        raise ValueError("SMTP_SERVER is not set in .env")
    if not smtp_username or not smtp_password:
        raise ValueError("SMTP_SENDER and SMTP_PASSWORD must be set in .env")
    if not sender_email:
        raise ValueError("SMTP_SENDER must be set in .env")

    if isinstance(recipients, str):
        recipient_list = [recipients]
    else:
        recipient_list = list(recipients)
    if not recipient_list:
        raise ValueError("At least one email recipient is required")

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipient_list)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    for file_path in attachments or []:
        path = Path(file_path)
        part = MIMEApplication(path.read_bytes(), Name=path.name)
        part["Content-Disposition"] = f'attachment; filename="{path.name}"'
        msg.attach(part)

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_username, smtp_password)
            server.sendmail(sender_email, recipient_list, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(sender_email, recipient_list, msg.as_string())

    return True
