"""Lead classification for Tanveer Associates real estate leads.

This encodes the exact stage rules written into the knowledge base
itself (see the "Lead Qualification Questions" category in
knowledge_base/company_data.py), so the bot's sales logic and the
knowledge it can quote to a user always agree with each other:

    new                                 -> conversation just started
    ready_for_call_missing_contact_details -> budget confirmed, but
                                            missing required contact info
    qualified_missing_call_time         -> budget confirmed + contact
                                            complete, but no call time yet
    qualified_ready_for_call            -> budget confirmed + contact
                                            complete + call time set
    not_interested                      -> property interest expressed,
                                            but budget/financing unknown

Still rule-based (no extra LLM call) -- fast, free, and fully
predictable, which matters a lot for a CRM field that a sales team will
actually filter and sort by.
"""

from typing import Optional

STAGE_NEW = "new"
STAGE_READY_FOR_CALL_MISSING_CONTACT = "ready_for_call_missing_contact_details"
STAGE_QUALIFIED_MISSING_CALL_TIME = "qualified_missing_call_time"
STAGE_QUALIFIED_READY_FOR_CALL = "qualified_ready_for_call"
STAGE_NOT_INTERESTED = "not_interested"

# Which contact fields are mandatory before a lead counts as "contact complete",
# per platform -- straight from company_data.py's "Lead Qualification Questions":
#   WhatsApp:  name only (phone is auto-captured from the sender's number)
#   Messenger: name + phone
#   Web chat:  name + phone (email stays optional)
REQUIRED_CONTACT_FIELDS = {
    "whatsapp": ["name"],
    "messenger": ["name", "phone"],
    "web": ["name", "phone"],
}

REQUIRED_EMAIL_FIELDS = (
    "name",
    "phone",
    "property_type",
    "city_or_area",
    "budget_range",
    "preferred_call_time",
    "site_visit_answered",
    "platform",
)


def _missing_contact_fields(platform: str, name: Optional[str], phone: Optional[str],
                             email: Optional[str]) -> list[str]:
    values = {"name": name, "phone": phone, "email": email}
    required = REQUIRED_CONTACT_FIELDS.get(platform, ["name", "phone"])
    return [field for field in required if not values.get(field)]


def classify_lead(
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
    site_visit_requested: bool = False,
    message_count: int = 0,
) -> dict:
    """Classify a lead and report exactly what's still needed to move it forward.

    Returns a dict with:
      stage           - one of the STAGE_* constants above
      score           - 0-100, for sorting/reporting (not used for staging logic)
      missing_fields  - what's still needed to advance to the next stage,
                        in the order the sales playbook asks for them
    """
    contact_missing = _missing_contact_fields(platform, name, phone, email)
    budget_confirmed = bool(budget_range)

    if not budget_confirmed:
        # A property question was likely asked, but we don't yet know if this
        # is a real buyer -- per the knowledge base this is "not_interested"
        # (i.e. not yet qualified), not a judgment that they dislike the property.
        stage = STAGE_NOT_INTERESTED
        missing = ["budget_range", "financing_method"] + contact_missing
    elif contact_missing:
        stage = STAGE_READY_FOR_CALL_MISSING_CONTACT
        missing = contact_missing
    elif not preferred_call_time:
        stage = STAGE_QUALIFIED_MISSING_CALL_TIME
        missing = ["preferred_call_time"]
    else:
        stage = STAGE_QUALIFIED_READY_FOR_CALL
        missing = []

    # Score is purely for sorting/reporting -- reward completeness so a
    # sales team can sort "leads" by how close they are to a booked call.
    score = 0
    score += 15 if name else 0
    score += 20 if phone else 0
    score += 5 if email else 0
    score += 10 if property_type else 0
    score += 10 if city_or_area else 0
    score += 20 if budget_confirmed else 0
    score += 10 if financing_method else 0
    score += 5 if purchase_timeline else 0
    score += 15 if preferred_call_time else 0
    score += 10 if site_visit_requested else 0
    score += min(message_count * 1, 10)  # small engagement bonus
    score = min(score, 100)

    return {"stage": stage, "score": score, "missing_fields": missing}
