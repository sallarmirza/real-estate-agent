
"""HTML email notification when a lead reaches the final stage."""

import os
import threading
from datetime import datetime
from html import escape
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from .email_module import send_email as dispatch


REPORT_RECIPIENTS = ["salar@m3hive.com"]
PAKISTAN_TZ = ZoneInfo("Asia/Karachi")


# (label, lead key) pairs displayed in the email, in this order.
LEAD_FIELDS = [
    ("Name", "name"),
    ("Phone", "phone"),
    ("Email", "email"),
    ("Property Type", "property_type"),
    ("City/Area", "city_or_area"),
    ("Budget", "budget_range"),
    ("Preferred Call Time", "preferred_call_time"),
]


def _lead_value(lead: dict, key: str) -> str:
    """Return a readable value for a lead field."""
    value = lead.get(key)

    if value is None or value == "":
        return "Not provided"

    if isinstance(value, (dict, list)):
        value = str(value)

    return str(value)


def _message_text(message: object) -> str:
    """Extract readable text from a LangChain conversation message."""
    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        text_parts = [
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        return "\n".join(text_parts).strip()

    return ""


def summarize_conversation(messages: Optional[Sequence[object]]) -> str:
    """Create a concise summary from the conversation messages available at lead capture."""
    transcript = []
    for message in messages or []:
        role = getattr(message, "type", "")
        text = _message_text(message)
        if role in {"human", "ai"} and text:
            transcript.append(f"{'Customer' if role == 'human' else 'Agent'}: {text}")

    if not transcript:
        return "No conversation messages were available when the lead notification was triggered."

    transcript_text = "\n".join(transcript)[-20000:]

    try:
        from langchain_openai import ChatOpenAI

        response = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
        ).invoke(
            "Summarize this real-estate lead conversation in up to four concise "
            "bullet points. Cover the customer's property interests, requirements "
            "or constraints, decisions, and any outstanding follow-up. Use only "
            "facts stated in the conversation; do not infer missing details.\n\n"
            f"{transcript_text}"
        )
        content = response.content
        if isinstance(content, str) and content.strip():
            return "\n".join(content.strip().splitlines()[:4])
        raise ValueError("Conversation summary model returned no text")
    except Exception as exc:
        print(f"Failed to summarize lead conversation: {exc}")
        return "Recent conversation:\n" + "\n".join(transcript[-4:])


def format_lead_text(lead: dict, conversation_summary: str = "") -> str:
    """Build the plain-text fallback email body."""

    reported_at = datetime.now(PAKISTAN_TZ).strftime(
        "%Y-%m-%d %H:%M PKT"
    )

    lines = [
        "M3HIVE REAL ESTATE AI AGENT",
        "NEW LEAD NOTIFICATION",
        "=" * 48,
        "",
        "A new potential customer has reached your lead notification stage.",
        "",
        "LEAD DETAILS",
        "-" * 48,
    ]

    for label, key in LEAD_FIELDS:
        lines.append(f"{label}: {_lead_value(lead, key)}")

    lines.extend([
        "",
        "CONVERSATION SUMMARY",
        "-" * 48,
        conversation_summary or "No conversation summary available.",
    ])

    lines.extend([
        "",
        "-" * 48,
        f"Reported at: {reported_at}",
        "Automated notification by M3Hive Real Estate AI Agent.",
    ])

    return "\n".join(lines)


def format_lead_html(lead: dict, conversation_summary: str = "") -> str:
    """Build a styled HTML email displayed directly in the inbox."""

    reported_at = datetime.now(PAKISTAN_TZ).strftime(
        "%d %b %Y, %I:%M %p PKT"
    )

    # Escape dynamic values to prevent HTML injection.
    lead_name = escape(_lead_value(lead, "name"))
    platform = escape(_lead_value(lead, "platform"))

    # Build the details table dynamically.
    rows = []

    for label, key in LEAD_FIELDS:
        safe_label = escape(label)
        safe_value = escape(_lead_value(lead, key))

        rows.append(f"""
            <tr>
                <td style="
                    padding: 12px 14px;
                    width: 40%;
                    color: #64748b;
                    font-size: 14px;
                    line-height: 1.5;
                    border-bottom: 1px solid #e8edf3;
                    vertical-align: top;
                ">
                    {safe_label}
                </td>
                <td style="
                    padding: 12px 14px;
                    color: #172b4d;
                    font-size: 14px;
                    line-height: 1.5;
                    font-weight: 500;
                    border-bottom: 1px solid #e8edf3;
                    overflow-wrap: anywhere;
                    word-break: break-word;
                ">
                    {safe_value}
                </td>
            </tr>
        """)

    fields_html = "\n".join(rows)
    summary_html = escape(
        conversation_summary or "No conversation summary available."
    ).replace("\n", "<br>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>M3Hive Real Estate AI - New Lead</title>
</head>
 <p style="
                                margin: 0 0 7px;
                                color: #64748b;
                                font-size: 12px;
                                line-height: 1.6;
                            ">
                                <strong>Reported at:</strong>
                                {escape(reported_at)}
                            </p>
<body style="
    margin: 0;
    padding: 24px 10px;
    background-color: #f1f5f9;
    font-family: Arial, Helvetica, sans-serif;
    color: #172b4d;
">

    <table role="presentation"
           width="100%"
           cellpadding="0"
           cellspacing="0"
           border="0">
        <tr>
            <td align="center">

                <table role="presentation"
                       width="100%"
                       cellpadding="0"
                       cellspacing="0"
                       border="0"
                       style="
                           max-width: 640px;
                           background-color: #ffffff;
                           border: 1px solid #e2e8f0;
                           border-radius: 10px;
                           overflow: hidden;
                       ">

                    <!-- HEADER -->
                    <tr>
                        <td style="
                            background-color: #163b5c;
                            padding: 28px 24px;
                            color: #ffffff;
                        ">
                            <p style="
                                margin: 0;
                                font-size: 12px;
                                letter-spacing: 2px;
                                color: #cbddec;
                                font-weight: bold;
                            ">
                                M3HIVE
                            </p>

                            <h1 style="
                                margin: 10px 0 6px;
                                font-size: 24px;
                                line-height: 1.3;
                                color: #ffffff;
                            ">
                                Real Estate AI Agent
                            </h1>

                            <p style="
                                margin: 0;
                                color: #d5e5f2;
                                font-size: 14px;
                                line-height: 1.5;
                            ">
                                New Lead Notification
                            </p>
                        </td>
                    </tr>

                    <!-- INTRODUCTION -->
                    <tr>
                        <td style="padding: 24px 24px 12px;">

                            <table role="presentation"
                                   width="100%"
                                   cellpadding="0"
                                   cellspacing="0"
                                   border="0">
                                <tr>
                                    <td valign="middle">
                                        <h2 style="
                                            margin: 0;
                                            font-size: 20px;
                                            line-height: 1.4;
                                            color: #163b5c;
                                        ">
                                            Lead Contact Details
                                        </h2>
                                    </td>

                                    <td align="right" valign="middle">
                                        <span style="
                                            display: inline-block;
                                            background-color: #dcfce7;
                                            color: #166534;
                                            padding: 6px 10px;
                                            border-radius: 20px;
                                            font-size: 11px;
                                            font-weight: bold;
                                            white-space: nowrap;
                                        ">
                                            NEW LEAD
                                        </span>
                                    </td>
                                </tr>
                            </table>

                            <p style="
                                margin: 10px 0 0;
                                color: #64748b;
                                font-size: 14px;
                                line-height: 1.7;
                            ">
                                A new potential customer has reached your
                                lead notification stage. Review the
                                information below for follow-up.
                            </p>
                        </td>
                    </tr>

                    <!-- LEAD SUMMARY -->
                    <tr>
                        <td style="padding: 12px 24px;">

                            <table role="presentation"
                                   width="100%"
                                   cellpadding="0"
                                   cellspacing="0"
                                   border="0"
                                   style="
                                       background-color: #f8fafc;
                                       border: 1px solid #e8edf3;
                                       border-radius: 8px;
                                   ">
                                <tr>
                                    <td width="50%"
                                        valign="top"
                                        style="padding: 14px;">

                                        <p style="
                                            margin: 0 0 6px;
                                            font-size: 11px;
                                            letter-spacing: 1px;
                                            color: #64748b;
                                        ">
                                            LEAD NAME
                                        </p>

                                        <p style="
                                            margin: 0;
                                            font-size: 17px;
                                            line-height: 1.5;
                                            font-weight: bold;
                                            color: #163b5c;
                                            overflow-wrap: anywhere;
                                        ">
                                            {lead_name}
                                        </p>
                                    </td>

                                    <td width="50%"
                                        valign="top"
                                        style="padding: 14px;">

                                        <p style="
                                            margin: 0 0 6px;
                                            font-size: 11px;
                                            letter-spacing: 1px;
                                            color: #64748b;
                                        ">
                                            CONTACT SOURCE
                                        </p>

                                        <p style="
                                            margin: 0;
                                            font-size: 14px;
                                            line-height: 1.5;
                                            font-weight: bold;
                                            color: #163b5c;
                                            overflow-wrap: anywhere;
                                        ">
                                            {platform}
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- LEAD INFORMATION -->
                    <tr>
                        <td style="padding: 18px 24px 26px;">

                            <h3 style="
                                margin: 0 0 14px;
                                font-size: 16px;
                                color: #163b5c;
                            ">
                                Lead Information
                            </h3>

                            <table role="presentation"
                                   width="100%"
                                   cellpadding="0"
                                   cellspacing="0"
                                   border="0"
                                   style="
                                       width: 100%;
                                       border: 1px solid #e8edf3;
                                       border-collapse: collapse;
                                   ">
                                {fields_html}
                            </table>

                        </td>
                    </tr>

                    <!-- CONVERSATION SUMMARY -->
                    <tr>
                        <td style="padding: 0 24px 24px;">
                            <h3 style="
                                margin: 0 0 10px;
                                font-size: 16px;
                                color: #163b5c;
                            ">
                                Conversation Summary
                            </h3>
                            <p style="
                                margin: 0;
                                padding: 14px;
                                background-color: #f8fafc;
                                border: 1px solid #e8edf3;
                                color: #172b4d;
                                font-size: 14px;
                                line-height: 1.7;
                            ">
                                {summary_html}
                            </p>
                        </td>
                    </tr>

                    <!-- FOOTER -->
                    <tr>
                        <td style="
                            background-color: #f8fafc;
                            border-top: 1px solid #e2e8f0;
                            padding: 20px 24px;
                        ">

                           

                            <p style="
                                margin: 0;
                                color: #64748b;
                                font-size: 12px;
                                line-height: 1.6;
                            ">
                                This is an automated notification from
                                M3Hive Real Estate AI Agent.
                            </p>

                        </td>
                    </tr>

                </table>

            </td>
        </tr>
    </table>

</body>
</html>"""


def _send(
    lead: dict,
    recipients: list[str],
    conversation_messages: Optional[Sequence[object]] = None,
) -> None:
    """Send the HTML report and plain-text fallback."""

    try:
        lead_name = _lead_value(lead, "name")
        platform = _lead_value(lead, "platform")
        conversation_summary = summarize_conversation(conversation_messages)

        sent = dispatch(
            subject=f"New Lead | {lead_name} | {platform}",
            body=format_lead_text(lead, conversation_summary),
            html_body=format_lead_html(lead, conversation_summary),
            recipients=recipients,
        )

        if not sent:
            raise ValueError("Email not sent")

    except Exception as exc:
        # The worker thread cannot propagate errors to the caller.
        print(f"Failed to send lead notification: {exc}")


def notify_contact_complete(
    lead: dict,
    recipients: Optional[list[str]] = None,
    conversation_messages: Optional[Sequence[object]] = None,
) -> None:
    """Queue an email notification without blocking lead updates."""

    if recipients is None:
        configured_recipients = os.getenv("REPORT_TO_EMAIL", "")

        recipients = [
            address.strip()
            for address in configured_recipients.split(",")
            if address.strip()
        ] or REPORT_RECIPIENTS

    if not recipients:
        raise ValueError(
            "At least one new-lead report recipient must be configured"
        )

    thread = threading.Thread(
        target=_send,
        args=(lead, recipients, conversation_messages),
        daemon=True,
        name="contact-complete-email",
    )
    thread.start()
