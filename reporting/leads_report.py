"""Email notification when a lead's required contact details are complete."""

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from .email_module import send_email as dispatch

logger = logging.getLogger(__name__)

REPORT_RECIPIENTS = ["salar@m3hive.com"]

# (label, lead key) pairs printed in the email, in this order
LEAD_FIELDS = [
    ("Name", "name"),
    ("Phone", "phone"),
    ("Email", "email"),
    ("Platform", "platform"),
    ("Property Type", "property_type"),
    ("City/Area", "city_or_area"),
    ("Budget", "budget_range"),
    ("Financing", "financing_method"),
    ("Timeline", "purchase_timeline"),
    ("Preferred Call Time", "preferred_call_time"),
    ("Site Visit Requested", "site_visit_requested"),
    ("Score", "score"),
    ("Handoff Requested", "handoff_requested"),
]


def format_lead_text(lead: dict) -> str:
    """Build the plain-text email body for a single lead."""
    lines = [
        "LEAD CONTACT DETAILS COMPLETED",
        f"Received at: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
        "",
    ]
    for label, key in LEAD_FIELDS:
        value = lead.get(key)
        lines.append(f"{label}: {value if value not in (None, '') else 'N/A'}")
    return "\n".join(lines)


def _send(lead: dict, recipients: list[str]) -> None:
    try:
        sent = dispatch(
            subject=f"New Lead | {lead.get('name') or 'Unknown'} | {lead.get('platform') or 'N/A'}",
            body=format_lead_text(lead),
            recipients=recipients,
        )
        if not sent:
            logger.error("New-lead email was not sent for user_id=%s", lead.get("user_id"))
    except Exception:
        logger.exception("Failed to send new-lead email for user_id=%s", lead.get("user_id"))


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
        threading.Thread(
            target=_send,
            args=(lead, recipients),
            daemon=True,
            name="contact-complete-email",
        ).start()
    except RuntimeError:
        logger.exception("Could not start new-lead email worker for user_id=%s", lead.get("user_id"))
