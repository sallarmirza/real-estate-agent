"""Email notification when a lead's required contact details are complete."""

import os
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from .email_module import send_email as dispatch

logger = logging.getLogger(__name__)

REPORT_RECIPIENTS = ["fadishah2456@gmail.com"]

# (label, lead key) pairs printed in the email, in this order
LEAD_FIELDS = [
    ("Name", "name"),
    ("Phone", "phone"),
   
    ("Platform", "platform"),
    ("Property Type", "property_type"),
    ("City/Area", "city_or_area"),
    ("Budget", "budget_range"),
    ("Preferred Call Time", "preferred_call_time"),
    ("Wants to Visit", "site_visit_answered"),
    
]


def format_lead_text(lead: dict) -> str:
    """Build the plain-text email body for a single lead."""
    lines = [
        "M3Hive Real Estate AI Agent",
        "LEAD CONTACT DETAILS ",
        f"Reported at: {datetime.now(ZoneInfo('Asia/Karachi')):%Y-%m-%d %H:%M PKT}",

        "",
    ]
    for label, key in LEAD_FIELDS:
        value = lead.get(key)
        lines.append(f"{label}: {value if value not in (None, '') else 'N/A'}")
    return "\n".join(lines)


def _send(lead: dict, recipients: list[str]) -> None:
    try:
        from memory.long_term_memory import get_lead

        latest_lead = get_lead(lead["user_id"], lead["platform"])
        if latest_lead is None:
            raise RuntimeError(
                f"Lead was not found in database for {lead['platform']}:{lead['user_id']}"
            )

        sent = dispatch(
            subject=(
                f"New Lead | {latest_lead.get('name') or 'Unknown'} "
                f"| {latest_lead.get('platform') or 'N/A'}"
            ),
            body=format_lead_text(latest_lead),
            recipients=recipients,
        )
        if sent:
            logger.info(
                "EMAIL SENT (SMTP accepted) for lead user_id=%s, recipient(s)=%s",
                lead.get("user_id"),
                ", ".join(recipients),
            )
        else:
            logger.error(
                "EMAIL NOT SENT for lead user_id=%s: SMTP send returned false",
                lead.get("user_id"),
            )
            _release_notification_claim(lead)
    except Exception:
        logger.exception(
            "EMAIL FAILED for lead user_id=%s",
            lead.get("user_id"),
        )
        _release_notification_claim(lead)


def _release_notification_claim(lead: dict) -> None:
    try:
        from memory.long_term_memory import release_contact_notification

        release_contact_notification(lead["user_id"], lead["platform"])
    except Exception:
        logger.exception(
            "Could not reset email notification status for user_id=%s",
            lead.get("user_id"),
        )


def notify_contact_complete(
    lead: dict,
    recipients: Optional[list[str]] = None,
) -> None:
    """Queue a notification email without blocking lead updates."""
    if recipients is None:
        configured_recipients = os.getenv("REPORT_TO_EMAIL", "")
        recipients = [
            address.strip()
            for address in configured_recipients.split(",")
            if address.strip()
        ] or REPORT_RECIPIENTS
    if not recipients:
        raise ValueError("At least one new-lead report recipient must be configured")

    try:
        logger.info(
            "Queueing new-lead email for user_id=%s, recipient(s)=%s",
            lead.get("user_id"),
            ", ".join(recipients),
        )
        threading.Thread(
            target=_send,
            args=(lead, recipients),
            daemon=True,
            name="contact-complete-email",
        ).start()
    except RuntimeError:
        logger.exception("Could not start new-lead email worker for user_id=%s", lead.get("user_id"))
        _release_notification_claim(lead)
