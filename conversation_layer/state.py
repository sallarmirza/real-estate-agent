"""The shape of data that flows through the LangGraph graph.

Every node reads from and/or writes to this state. LangGraph's
PostgresSaver checkpointer (memory/short_term_memory.py) persists this
whole object between turns, keyed by thread_id -- that's what gives the
agent memory without us re-sending history by hand.

Field names mirror lead_intelligence/lead_schema.py (the CRM record) so
mapping between "live conversation state" and "stored lead" stays 1:1.
"""

from typing import Annotated, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    # `add_messages` is a reducer: new messages returned by a node are
    # appended to this list rather than replacing it.
    messages: Annotated[list, add_messages]

    # Which channel this conversation is happening on.
    platform: str  # "whatsapp" | "messenger" | "web"

    # Stable identifier for the person: WhatsApp phone number, Messenger
    # PSID, or a generated web session id.
    user_id: str

    # Contact info, filled in over time by the save_lead_info tool.
    user_name: Optional[str]
    user_phone: Optional[str]
    user_email: Optional[str]

    # Property qualification info (see lead_intelligence/lead_scoring.py).
    property_type: Optional[str]
    city_or_area: Optional[str]
    budget_range: Optional[str]
    financing_method: Optional[str]
    purchase_timeline: Optional[str]
    preferred_call_time: Optional[str]
    site_visit_requested: bool
    site_visit_answered: bool

    # Lead intelligence, updated by save_lead_info.
    lead_stage: str   # see lead_intelligence/lead_scoring.py STAGE_* constants
    lead_score: int   # 0-100

    # Human handoff flag, set by the escalate_to_human tool.
    handoff_requested: bool
    handoff_reason: Optional[str]
