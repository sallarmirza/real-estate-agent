"""Facebook Messenger webhook (Meta Graph API, page-level events).

Returns 200 immediately and processes messages in background tasks —
same reasoning as whatsapp_webhook.py: Meta retries on slow responses.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from app.settings import META_VERIFY_TOKEN
from conversation_layer.graph import run_turn
from webhook.message_sender import send_messenger_message

logger = logging.getLogger("tanveer.messenger_webhook")

router = APIRouter(prefix="/webhook/messenger", tags=["messenger"])


@router.get("")
def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


async def _process_and_reply(text: str, sender_id: str) -> None:
    """Run the agent and send the reply. Executed as a background task."""
    try:
        reply = await asyncio.to_thread(run_turn, text, "messenger", sender_id)
    except Exception:
        logger.exception("Agent failed on Messenger message from %s", sender_id)
        reply = "Sorry, something went wrong on our end. Please try again shortly."
    await send_messenger_message(sender_id, reply)


@router.post("")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()

    if body.get("object") != "page":
        return {"status": "ignored"}

    for entry in body.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            if not sender_id:
                continue

            message = event.get("message", {})

            if "text" in message:
                text = message["text"].strip()
                if not text:
                    continue
                background_tasks.add_task(_process_and_reply, text, sender_id)

            elif "attachments" in message:
                background_tasks.add_task(
                    send_messenger_message,
                    sender_id,
                    "Sorry, I can only process text messages right now.",
                )

            elif "postback" in event:
                payload = event["postback"].get("payload", "")
                if payload:
                    background_tasks.add_task(_process_and_reply, payload, sender_id)

    return {"status": "ok"}
