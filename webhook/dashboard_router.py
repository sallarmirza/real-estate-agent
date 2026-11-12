"""Dashboard API endpoints consumed by the leadhive-ai-web frontend."""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Query
from psycopg.rows import dict_row

from memory.long_term_memory import _get_pool
from app.settings import MESSENGER_PAGE_ACCESS_TOKEN, WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID

router = APIRouter(prefix="/estate")


@router.get("/stats")
def get_stats():
    """Aggregate counts for the dashboard overview cards."""
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT
                    COUNT(*)                                                             AS total_leads,
                    COUNT(CASE WHEN stage NOT IN ('new', 'not_interested') THEN 1 END)  AS engaged_users,
                    COUNT(CASE WHEN stage LIKE 'qualified%%' THEN 1 END)                AS qualified_leads,
                    COUNT(CASE WHEN handoff_requested = TRUE THEN 1 END)                AS handoff_requested,
                    COALESCE(SUM(message_count), 0)                                     AS total_messages
                FROM leads
            """)
            row = cur.fetchone()
    return dict(row)


@router.get("/leads")
def get_leads(limit: int = Query(default=20, ge=1, le=200)):
    """Most recently updated leads — key fields only."""
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT user_id, platform, name, phone, email,
                       property_type, city_or_area, budget_range,
                       preferred_call_time, stage, score, message_count,
                       handoff_requested, updated_at
                FROM leads
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    result = []
    for row in rows:
        r = dict(row)
        if r.get("updated_at") is not None:
            r["updated_at"] = r["updated_at"].isoformat()
        result.append(r)
    return result


@router.get("/engagement")
def get_engagement():
    """Bucket leads by message_count relative to the most active lead."""
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT user_id, platform, message_count,
                       (stage LIKE 'qualified%%') AS is_qualified
                FROM leads
                ORDER BY message_count DESC
            """)
            rows = cur.fetchall()

    if not rows:
        return {"total_users": 0, "buckets": []}

    threshold = rows[0]["message_count"] or 0
    total_users = len(rows)

    buckets = [
        {"label": "Complete Engagement (>75%)",   "users": 0, "qualified": 0},
        {"label": "Good Engagement (50-75%)",      "users": 0, "qualified": 0},
        {"label": "Moderate Engagement (25-50%)",  "users": 0, "qualified": 0},
        {"label": "Low Engagement (<25%)",         "users": 0, "qualified": 0},
    ]

    for row in rows:
        pct = (row["message_count"] / threshold * 100) if threshold > 0 else 0
        is_q = bool(row["is_qualified"])

        if pct > 75:
            b = buckets[0]
        elif pct >= 50:
            b = buckets[1]
        elif pct >= 25:
            b = buckets[2]
        else:
            b = buckets[3]

        b["users"] += 1
        if is_q:
            b["qualified"] += 1

    for b in buckets:
        b["percentage"] = round((b["users"] / total_users * 100), 2) if total_users > 0 else 0.0

    return {"total_users": total_users, "buckets": buckets}


@router.get("/page-info")
def get_page_info():
    """Check Facebook and WhatsApp connection status."""
    result = {}

    # Facebook
    if MESSENGER_PAGE_ACCESS_TOKEN:
        try:
            resp = httpx.get(
                "https://graph.facebook.com/v23.0/me",
                params={"fields": "id,name,link", "access_token": MESSENGER_PAGE_ACCESS_TOKEN},
                timeout=5,
            )
            data = resp.json()
            if "error" in data:
                result["facebook"] = {"connected": False, "reason": data["error"].get("message", "Token error")}
            else:
                result["facebook"] = {
                    "connected": True,
                    "page_id":   data.get("id"),
                    "page_name": data.get("name"),
                    "page_link": data.get("link"),
                }
        except Exception as e:
            result["facebook"] = {"connected": False, "reason": str(e)}
    else:
        result["facebook"] = {"connected": False, "reason": "PAGE_ACCESS_TOKEN not set"}

    # WhatsApp
    if WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
        try:
            resp = httpx.get(
                f"https://graph.facebook.com/v23.0/{WHATSAPP_PHONE_NUMBER_ID}",
                params={"fields": "display_phone_number,verified_name"},
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
                timeout=5,
            )
            data = resp.json()
            if "error" in data:
                result["whatsapp"] = {"connected": False, "reason": data["error"].get("message", "Token error")}
            else:
                result["whatsapp"] = {
                    "connected": True,
                    "number":    data.get("display_phone_number"),
                    "name":      data.get("verified_name"),
                }
        except Exception as e:
            result["whatsapp"] = {"connected": False, "reason": str(e)}
    else:
        result["whatsapp"] = {"connected": False, "reason": "WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID not set"}

    return result
