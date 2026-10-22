"""Pydantic model for a Tanveer Associates real estate lead.

Field choices come straight from the "Lead Qualification Questions"
category in knowledge_base/company_data.py -- that section is the actual
sales playbook (what to ask, in what order, and how leads get staged),
and this schema mirrors it so the data we store matches how the business
already thinks about a lead.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Lead(BaseModel):
    user_id: str
    platform: str  # "whatsapp" | "messenger" | "web"

    # Contact info -- which of these are required depends on platform,
    # see lead_intelligence/lead_scoring.py:REQUIRED_CONTACT_FIELDS.
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

    # Property qualification questions (from company_data.py).
    property_type: Optional[str] = None      # residential | commercial | plot
    city_or_area: Optional[str] = None       # e.g. "E-11, Islamabad", "Faisal Town"
    budget_range: Optional[str] = None       # e.g. "80-100 lac", "1.5 crore"
    financing_method: Optional[str] = None   # bank financing | installment plan | cash
    purchase_timeline: Optional[str] = None  # immediate | few_months

    # Scheduling
    preferred_call_time: Optional[str] = None
    site_visit_requested: bool = False
    site_visit_answered: bool = False

    notes: Optional[str] = None

    # Derived
    stage: str = "new"
    score: int = 0
    message_count: int = 0
    handoff_requested: bool = False
    handoff_reason: Optional[str] = None

    created_at: datetime
    updated_at: datetime
