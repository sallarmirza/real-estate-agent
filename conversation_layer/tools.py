"""Tools available to the agent, run through LangGraph's ToolNode.

1. search_knowledge_base  -> customer support (RAG, always runs before
                              the model answers a property/company question)
2. save_lead_info         -> lead management. This is the "intelligent"
                              one: it auto-fills the phone number on
                              WhatsApp, validates email/phone format,
                              merges with what's already known, classifies
                              the lead stage using the exact rules from
                              company_data.py's "Lead Qualification
                              Questions" section, and tells the model
                              precisely what's still missing so it asks
                              for the right thing next -- instead of
                              re-asking for info it already has.
3. escalate_to_human      -> handoff to a human agent.
"""

import re
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from knowledge_base.retriever import format_context, retrieve_documents
from lead_intelligence.lead_scoring import classify_lead
from memory.long_term_memory import mark_handoff, upsert_lead

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _looks_like_valid_phone(phone: str) -> bool:
    """Loose check: at least 10 digits once punctuation/spaces are stripped."""
    digits = re.sub(r"[^\d]", "", phone)
    return len(digits) >= 10


@tool
def search_knowledge_base(query: str) -> str:
    """Search Tanveer Associates' knowledge base for information about
    projects, pricing/payment plans, locations, amenities, company
    background, or any other company-related question. Always call this
    before answering a question about Tanveer Associates -- never answer
    from memory.
    """
    documents = retrieve_documents(query)
    return format_context(documents)


@tool
def save_lead_info(
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
    notes: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Save or update anything you've learned about this lead: contact
    details (name, phone, email), property interest (property_type,
    city_or_area), qualification info (budget_range, financing_method,
    purchase_timeline), or scheduling (preferred_call_time,
    site_visit_requested). Call this as soon as the user shares any of
    these, even one field at a time -- it merges with what's already
    known rather than overwriting it. On WhatsApp you do not need to ask
    for a phone number; it is captured automatically from the sender.
    After calling this, only ask the user for whatever this tool reports
    as still missing -- never re-ask for something already saved.
    """
    user_id = state["user_id"]
    platform = state["platform"]

    warnings = []

    # WhatsApp: the sender's phone number IS the user_id, so we never need
    # to ask for it -- auto-fill it the first time we save anything for them.
    if platform == "whatsapp" and not phone and not state.get("user_phone"):
        phone = user_id

    if email and not _EMAIL_RE.match(email):
        warnings.append(f"'{email}' doesn't look like a valid email, so it wasn't saved.")
        email = None

    if phone and not _looks_like_valid_phone(phone):
        warnings.append(f"'{phone}' doesn't look like a valid phone number, so it wasn't saved.")
        phone = None

    merged = {
        "name": name or state.get("user_name"),
        "phone": phone or state.get("user_phone"),
        "email": email or state.get("user_email"),
        "property_type": property_type or state.get("property_type"),
        "city_or_area": city_or_area or state.get("city_or_area"),
        "budget_range": budget_range or state.get("budget_range"),
        "financing_method": financing_method or state.get("financing_method"),
        "purchase_timeline": purchase_timeline or state.get("purchase_timeline"),
        "preferred_call_time": preferred_call_time or state.get("preferred_call_time"),
        "site_visit_requested": (
            site_visit_requested if site_visit_requested is not None
            else state.get("site_visit_requested", False)
        ),
    }

    classification = classify_lead(
        platform=platform,
        message_count=len(state.get("messages", [])),
        **merged,
    )
    stage, score, missing_fields = (
        classification["stage"], classification["score"], classification["missing_fields"]
    )

    upsert_lead(
        user_id=user_id,
        platform=platform,
        notes=notes,
        stage=stage,
        score=score,
        message_count=sum(
            1 for message in state.get("messages", [])
            if getattr(message, "type", None) == "human"
        ),
        site_visit_answered=site_visit_requested is not None,
        **merged,
    )

    status_line = f"Lead saved. stage={stage}, score={score}."
    if missing_fields:
        status_line += f" Still missing (ask for this next, only what's listed): {', '.join(missing_fields)}."
    else:
        status_line += " All qualification info is complete -- confirm the call time/site visit with the user."
    if warnings:
        status_line += " " + " ".join(warnings)

    return Command(
        update={
            "user_name": merged["name"],
            "user_phone": merged["phone"],
            "user_email": merged["email"],
            "property_type": merged["property_type"],
            "city_or_area": merged["city_or_area"],
            "budget_range": merged["budget_range"],
            "financing_method": merged["financing_method"],
            "purchase_timeline": merged["purchase_timeline"],
            "preferred_call_time": merged["preferred_call_time"],
            "site_visit_requested": merged["site_visit_requested"],
            "lead_stage": stage,
            "lead_score": score,
            "messages": [ToolMessage(content=status_line, tool_call_id=tool_call_id)],
        }
    )


@tool
def escalate_to_human(
    reason: str,
    state: Annotated[dict, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Flag this conversation for a human sales agent to take over. Use
    this when: the user explicitly asks for a human/agent, wants to
    negotiate price, is upset or complaining, or asks something outside
    what the knowledge base covers (e.g. legal/contract specifics). After
    calling this, tell the user a specialist will follow up shortly --
    do not keep answering on their behalf.
    """
    mark_handoff(user_id=state["user_id"], platform=state["platform"], reason=reason)

    return Command(
        update={
            "handoff_requested": True,
            "handoff_reason": reason,
            "messages": [
                ToolMessage(
                    content="Conversation flagged for human follow-up.",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


TOOLS = [search_knowledge_base, save_lead_info, escalate_to_human]
