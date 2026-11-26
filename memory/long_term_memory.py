"""Long-term memory: the leads/CRM store, now backed by PostgreSQL.

This is intentionally separate from short_term_memory.py:
- short_term_memory (LangGraph's PostgresSaver checkpointer) = "what did
  we say to each other" -- the raw conversation.
- long_term_memory (this file)  = "who is this person, structurally" --
  name, phone, budget, stage, etc. A real CRM table.

Uses a single shared connection pool (psycopg_pool) rather than opening a
new connection per call, since this runs inside a request-serving app.
"""

import os
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Sequence

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from lead_intelligence.lead_scoring import (
    REQUIRED_CONTACT_FIELDS,
    STAGE_QUALIFIED_READY_FOR_CALL,
)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:687254@localhost:5432/tanveer_associates"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    user_id               TEXT NOT NULL,
    platform              TEXT NOT NULL,
    name                  TEXT,
    phone                 TEXT,
    email                 TEXT,
    property_type         TEXT,
    city_or_area          TEXT,
    budget_range          TEXT,
    financing_method      TEXT,
    purchase_timeline     TEXT,
    preferred_call_time   TEXT,
    site_visit_requested  BOOLEAN NOT NULL DEFAULT FALSE,
    site_visit_answered   BOOLEAN NOT NULL DEFAULT FALSE,
    notes                 TEXT,
    stage                 TEXT NOT NULL DEFAULT 'new',
    score                 INTEGER NOT NULL DEFAULT 0,
    message_count         INTEGER NOT NULL DEFAULT 0,
    handoff_requested     BOOLEAN NOT NULL DEFAULT FALSE,
    handoff_reason        TEXT,
    contact_reported_at   TIMESTAMPTZ,
    final_stage_reported_at TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL,
    updated_at             TIMESTAMPTZ NOT NULL,
    summary               TEXT,
    PRIMARY KEY (user_id, platform)
);
CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads (stage);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS contact_reported_at TIMESTAMPTZ;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS site_visit_answered BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS final_stage_reported_at TIMESTAMPTZ;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS summary TEXT;
CREATE TABLE IF NOT EXISTS user_activity (
    user_id          TEXT NOT NULL,
    platform         TEXT NOT NULL,
    message_count    INTEGER NOT NULL DEFAULT 0,
    first_message_at TIMESTAMPTZ NOT NULL,
    last_message_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, platform)
);
INSERT INTO user_activity (user_id, platform, message_count, first_message_at, last_message_at)
SELECT user_id, platform, message_count, created_at, updated_at
FROM leads
WHERE message_count > 0
ON CONFLICT (user_id, platform) DO NOTHING;
"""

_pool: Optional[ConnectionPool] = None
logger = logging.getLogger(__name__)
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d(?:[\s().-]*\d){9,14}(?!\w)")


def mask_phone_numbers(text: str) -> str:
    """Keep only the first four and last three digits of phone numbers."""
    def mask(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group())
        if len(digits) == 12 and digits.startswith("92"):
            digits = "0" + digits[2:]
        return f"{digits[:4]} **** {digits[-3:]}"

    return _PHONE_PATTERN.sub(mask, text)


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=True)
        with _pool.connection() as conn:
            conn.execute(_SCHEMA)
            for platform, fields in REQUIRED_CONTACT_FIELDS.items():
                complete_condition = " AND ".join(
                    f"NULLIF(BTRIM({field}), '') IS NOT NULL" for field in fields
                )
                conn.execute(
                    f"""
                    UPDATE leads
                    SET contact_reported_at = updated_at
                    WHERE platform = %s
                      AND contact_reported_at IS NULL
                      AND {complete_condition}
                    """,
                    (platform,),
                )
            conn.commit()
    return _pool


def get_lead(user_id: str, platform: str) -> Optional[dict]:
    """Fetch a stored lead record, or None if this person is brand new."""
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM leads WHERE user_id = %s AND platform = %s",
                (user_id, platform),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def upsert_lead(
    user_id: str,
    platform: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    property_type: Optional[str] = None,
    city_or_area: Optional[str] = None,
    budget_range: Optional[str] = None,
    financing_method: Optional[str] = None,
    purchase_timeline: Optional[str] = None,
    preferred_call_time: Optional[str] = None,
    site_visit_requested: Optional[bool] = None,
    site_visit_answered: Optional[bool] = None,
    notes: Optional[str] = None,
    stage: Optional[str] = None,
    score: Optional[int] = None,
    message_count: Optional[int] = None,
) -> Optional[dict]:
    """Create or update a lead record. Only overwrites fields that are provided.

    Uses PostgreSQL's INSERT ... ON CONFLICT for a proper atomic upsert
    (rather than a manual "does it exist? update else insert" round trip).
    """
    now = datetime.now(timezone.utc)
    pool = _get_pool()

    existing = get_lead(user_id, platform) or {}
    effective_name = name or existing.get("name")
    effective_phone = phone or existing.get("phone")
    if not (effective_name and effective_name.strip() and effective_phone and effective_phone.strip()):
        return None

    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO leads (
                user_id, platform, name, phone, email, property_type,
                city_or_area, budget_range, financing_method, purchase_timeline,
                preferred_call_time, site_visit_requested, site_visit_answered,
                notes, stage, score, message_count, contact_reported_at,
                final_stage_reported_at, created_at, updated_at
            )
            VALUES (
                %(user_id)s, %(platform)s, %(name)s, %(phone)s, %(email)s,
                %(property_type)s, %(city_or_area)s, %(budget_range)s,
                %(financing_method)s, %(purchase_timeline)s, %(preferred_call_time)s,
                COALESCE(%(site_visit_requested)s, FALSE),
                COALESCE(%(site_visit_answered)s, FALSE), %(notes)s,
                COALESCE(%(stage)s, 'new'), COALESCE(%(score)s, 0),
                COALESCE(
                    (SELECT message_count FROM user_activity
                     WHERE user_id = %(user_id)s AND platform = %(platform)s),
                    %(message_count)s, 0
                ), NULL, NULL, %(now)s, %(now)s
            )
            ON CONFLICT (user_id, platform) DO UPDATE SET
                name                 = COALESCE(EXCLUDED.name, leads.name),
                phone                = COALESCE(EXCLUDED.phone, leads.phone),
                email                = COALESCE(EXCLUDED.email, leads.email),
                property_type        = COALESCE(EXCLUDED.property_type, leads.property_type),
                city_or_area         = COALESCE(EXCLUDED.city_or_area, leads.city_or_area),
                budget_range         = COALESCE(EXCLUDED.budget_range, leads.budget_range),
                financing_method     = COALESCE(EXCLUDED.financing_method, leads.financing_method),
                purchase_timeline    = COALESCE(EXCLUDED.purchase_timeline, leads.purchase_timeline),
                preferred_call_time  = COALESCE(EXCLUDED.preferred_call_time, leads.preferred_call_time),
                site_visit_requested = COALESCE(%(site_visit_requested)s, leads.site_visit_requested),
                site_visit_answered  = leads.site_visit_answered OR EXCLUDED.site_visit_answered,
                notes                = COALESCE(EXCLUDED.notes, leads.notes),
                stage                = COALESCE(EXCLUDED.stage, leads.stage),
                score                = COALESCE(EXCLUDED.score, leads.score),
                message_count        = COALESCE(
                    (SELECT message_count FROM user_activity
                     WHERE user_id = %(user_id)s AND platform = %(platform)s),
                    EXCLUDED.message_count
                ),
                updated_at           = EXCLUDED.updated_at,
                summary              = COALESCE(leads.summary, EXCLUDED.summary)
            """,
            {
                "user_id": user_id, "platform": platform, "name": name, "phone": phone,
                "email": email, "property_type": property_type, "city_or_area": city_or_area,
                "budget_range": budget_range, "financing_method": financing_method,
                "purchase_timeline": purchase_timeline, "preferred_call_time": preferred_call_time,
                "site_visit_requested": site_visit_requested,
                "site_visit_answered": site_visit_answered, "notes": notes,
                "stage": stage, "score": score, "message_count": message_count, "now": now,
            },
        )
        required_contact_fields = REQUIRED_CONTACT_FIELDS.get(platform, ["name", "phone"])
        complete_condition = " AND ".join(
            f"NULLIF(BTRIM({field}), '') IS NOT NULL"
            for field in required_contact_fields
        )
        notification_claim = conn.execute(
            f"""
            UPDATE leads
            SET final_stage_reported_at = %s
            WHERE user_id = %s
              AND platform = %s
              AND final_stage_reported_at IS NULL
              AND stage = %s
              AND site_visit_answered IS TRUE
              AND NULLIF(BTRIM(preferred_call_time), '') IS NOT NULL
              AND {complete_condition}
            RETURNING TRUE
            """,
            (now, user_id, platform, STAGE_QUALIFIED_READY_FOR_CALL),
        )
        should_notify = notification_claim.fetchone() is not None
        conn.commit()

    lead = get_lead(user_id, platform)
    if lead is None:
        raise RuntimeError(f"Lead upsert succeeded but lead was not found for {platform}:{user_id}")

    if should_notify:
        from app.settings import REPORTING_ENABLED
        if REPORTING_ENABLED:
            from reporting.leads_report import notify_contact_complete
            notify_contact_complete(lead, conversation_messages=conversation_messages)
        else:
            print(f"[reporting disabled] Lead {platform}:{user_id} reached final stage — skipping email.")
    return lead


def update_lead_summary(
    user_id: str,
    platform: str,
    conversation_messages: Sequence[object],
) -> Optional[str]:
    """Refresh a complete lead's summary and notify the live dashboard."""
    lead = get_lead(user_id, platform)
    if not lead or not (lead.get("name") or "").strip() or not (lead.get("phone") or "").strip():
        return None

    try:
        from reporting.leads_report import summarize_conversation

        summary = summarize_conversation(conversation_messages)
        if not summary:
            return None
        summary = mask_phone_numbers(summary)
        now = datetime.now(timezone.utc)
        pool = _get_pool()
        with pool.connection() as conn:
            conn.execute(
                """
                UPDATE leads
                SET summary = %s, updated_at = %s
                WHERE user_id = %s AND platform = %s
                  AND NULLIF(BTRIM(name), '') IS NOT NULL
                  AND NULLIF(BTRIM(phone), '') IS NOT NULL
                """,
                (summary, now, user_id, platform),
            )
            conn.commit()
        from webhook.dashboard_events import publish_dashboard_event
        publish_dashboard_event()
        return summary
    except Exception:
        logger.exception("Lead summary refresh failed for %s:%s", platform, user_id)
        return None


def increment_message_count(user_id: str, platform: str) -> None:
    """Track every inbound user, whether or not they have shared contact details."""
    now = datetime.now(timezone.utc)
    pool = _get_pool()
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO user_activity (
                user_id, platform, message_count, first_message_at, last_message_at
            )
            VALUES (%s, %s, 1, %s, %s)
            ON CONFLICT (user_id, platform) DO UPDATE SET
                message_count = user_activity.message_count + 1,
                last_message_at = EXCLUDED.last_message_at
            """,
            (user_id, platform, now, now),
        )
        conn.execute(
            """
            UPDATE leads
            SET message_count = (
                    SELECT message_count FROM user_activity
                    WHERE user_id = %s AND platform = %s
                ),
                updated_at = %s
            WHERE user_id = %s AND platform = %s
            """,
            (user_id, platform, now, user_id, platform),
        )
        conn.commit()
    from webhook.dashboard_events import publish_dashboard_event
    publish_dashboard_event()


def mark_handoff(user_id: str, platform: str, reason: str) -> None:
    """Flag a conversation as needing a human agent (used by escalate_to_human)."""
    now = datetime.now(timezone.utc)
    pool = _get_pool()
    with pool.connection() as conn:
        conn.execute(
            "UPDATE leads SET handoff_requested = TRUE, handoff_reason = %s, updated_at = %s "
            "WHERE user_id = %s AND platform = %s",
            (reason, now, user_id, platform),
        )
        conn.commit()
    from webhook.dashboard_events import publish_dashboard_event
    publish_dashboard_event()


def list_leads(stage: Optional[str] = None) -> list[dict]:
    """List all leads, optionally filtered by stage. Used by reporting/."""
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if stage:
                cur.execute("SELECT * FROM leads WHERE stage = %s ORDER BY updated_at DESC", (stage,))
            else:
                cur.execute("SELECT * FROM leads ORDER BY updated_at DESC")
            return [dict(row) for row in cur.fetchall()]
