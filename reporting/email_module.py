import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable, Optional, Union

from dotenv import load_dotenv


# Load .env from the project root directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env",override=True)


def send_email(
    subject: str,
    body: str,
    recipients: Union[str, Iterable[str]],
    attachments: Optional[Iterable[str]] = None,
    html_body: Optional[str] = None,
) -> bool:
    """Send an email using SMTP, optionally including file attachments."""

    smtp_host = (
        os.getenv("SMTP_SERVER")
        or os.getenv("SMTP_HOST")
    )
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = (
        os.getenv("SMTP_SENDER")
        or os.getenv("SMTP_USERNAME")
    )
    smtp_password = os.getenv("SMTP_PASSWORD")
    sender_email = (
        os.getenv("SMTP_SENDER")
        or os.getenv("REPORT_FROM_EMAIL")
        or smtp_username
    )

    # Validate SMTP configuration.
    if not smtp_host:
        raise ValueError("SMTP_SERVER or SMTP_HOST is not set in .env")

    if not smtp_username:
        raise ValueError("SMTP_SENDER or SMTP_USERNAME is not set in .env")

    if not smtp_password:
        raise ValueError("SMTP_PASSWORD is not set in .env")

    if not sender_email:
        raise ValueError("Sender email is not configured")

    # Normalize recipients.
    if isinstance(recipients, str):
        recipient_list = [recipients]
    else:
        recipient_list = list(recipients)

    if not recipient_list:
        raise ValueError("At least one email recipient is required")

    # Create the email.
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipient_list)
    msg["Subject"] = subject

    if html_body is None:
        msg.attach(MIMEText(body, "plain", "utf-8"))
    else:
        alternatives = MIMEMultipart("alternative")
        alternatives.attach(MIMEText(body, "plain", "utf-8"))
        alternatives.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(alternatives)

    # Add optional attachments.
    for file_path in attachments or []:
        path = Path(file_path)

        if not path.is_file():
            raise FileNotFoundError(
                f"Attachment not found: {path}"
            )

        part = MIMEApplication(
            path.read_bytes(),
            Name=path.name,
        )
        part["Content-Disposition"] = (
            f'attachment; filename="{path.name}"'
        )
        msg.attach(part)

 

    try:
        # Port 465 uses implicit SSL.
        if smtp_port == 465:
            with smtplib.SMTP_SSL(
                smtp_host,
                smtp_port,
                timeout=30,
            ) as server:
                server.login(smtp_username, smtp_password)
                server.sendmail(
                    sender_email,
                    recipient_list,
                    msg.as_string(),
                )

        # Port 587 normally uses STARTTLS.
        else:
            with smtplib.SMTP(
                smtp_host,
                smtp_port,
                timeout=30,
            ) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_username, smtp_password)
                server.sendmail(
                    sender_email,
                    recipient_list,
                    msg.as_string(),
                )

        print(f"Email sent successfully to: {', '.join(recipient_list)}")
        return True

    except smtplib.SMTPAuthenticationError:
        print(
            "SMTP authentication failed. Check the mailbox username, "
            "password, and SMTP provider settings."
        )
        raise

    except (smtplib.SMTPException, OSError) as exc:
        print(f"SMTP email sending failed: {exc}")
        raise