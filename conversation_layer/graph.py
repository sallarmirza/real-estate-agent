"""The LangGraph graph itself.

Shape (classic tool-calling loop, built explicitly with ToolNode instead
of a prebuilt helper, so it's easy to see/extend):

    START -> agent --(tool calls?)--> tools -> agent -> ... -> END
                 \\--(no tool calls)-----------------------> END

- "agent"  : one ChatOpenAI call, bound to TOOLS, with a system prompt
             built fresh from current state (system_prompt.py).
- "tools"  : LangGraph's ToolNode. Executes whichever tool(s) the model
             asked for (search_knowledge_base / save_lead_info /
             escalate_to_human) and appends their results as
             ToolMessages, then loops back to "agent".

Memory:
- Short-term (this conversation's messages) is handled entirely by the
  SqliteSaver checkpointer -- we never manually resend history.
- Long-term (name/phone/email/lead stage) is loaded from the CRM store
  into the initial state in run_turn(), and written back to it by the
  save_lead_info / escalate_to_human tools as the conversation goes.
"""

import os
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from conversation_layer.state import AgentState
from conversation_layer.system_prompt import build_system_prompt
from conversation_layer.tools import TOOLS
from lead_intelligence.lead_scoring import classify_lead
from memory.long_term_memory import (
    get_lead,
    increment_message_count,
    update_lead_summary,
    upsert_lead,
)
from memory.short_term_memory import build_thread_id, get_checkpointer

from langchain_openai import ChatOpenAI

_llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.2")),
).bind_tools(TOOLS, parallel_tool_calls=False)


def call_model(state: AgentState) -> dict:
    """The 'agent' node: one LLM turn, grounded by a fresh system prompt."""
    system = SystemMessage(content=build_system_prompt(state))
    response = _llm.invoke([system] + state["messages"])
    return {"messages": [response]}


def _build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(TOOLS))

    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", END: END},
    )
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=get_checkpointer())


# Compiled once per process; the checkpointer makes every .invoke() call
# below resume the right conversation as long as thread_id matches.
_compiled_graph = _build_graph()


def _ensure_property_questions(answer: str, state: dict) -> str:
    missing = []
    lower_answer = answer.lower()

    if not state.get("property_type"):
        asked_property_type = (
            any(term in lower_answer for term in (
                "property type", "type of property", "residential", "commercial", "plot",
            ))
            and any(term in lower_answer for term in ("what", "which", "looking for", "interested"))
        )
        if not asked_property_type:
            missing.append(
                "What type of property are you looking for: residential, commercial, or a plot?"
            )

    if not state.get("city_or_area"):
        asked_location = (
            any(term in lower_answer for term in ("city", "area", "location", "where"))
            and any(term in lower_answer for term in ("what", "which", "where", "prefer", "looking"))
        )
        if not asked_location:
            missing.append("Which city or area do you prefer?")

    if not missing:
        return answer
    return answer.rstrip() + "\n\n" + " ".join(missing)


def _capture_pending_answers(message: str, pending_fields: list[str]) -> dict[str, str]:
    text = message.strip()
    lower_text = text.lower()
    captured = {}
    if not text or "?" in text or any(
        phrase in lower_text for phrase in ("how much", "what is", "tell me", "price", "payment")
    ):
        return captured

    property_type = None
    if "property_type" in pending_fields:
        if any(term in lower_text for term in ("commercial", "office", "shop")):
            property_type = "commercial"
        elif any(term in lower_text for term in ("plot", "land")):
            property_type = "plot"
        elif any(term in lower_text for term in ("residential", "house", "home", "apartment", "flat")):
            property_type = "residential"
        if property_type:
            captured["property_type"] = property_type

    if "city_or_area" in pending_fields and not any(
        term in lower_text for term in ("budget", "installment", "financing", "cash", "price")
    ):
        location = text
        location = re.sub(
            r"^(?:i(?:'m| am)?\s+)?(?:looking|interested)\s+(?:for|in|at)\s+",
            "",
            location,
            flags=re.IGNORECASE,
        )
        location = re.sub(r"^(?:my\s+)?(?:city|area|location)\s+(?:is|:)\s*", "", location, flags=re.IGNORECASE)
        if property_type:
            location = re.sub(
                r"\b(?:commercial|office|shop|plot|land|residential|house|home|apartment|flat)\b",
                "",
                location,
                flags=re.IGNORECASE,
            )
        location = re.sub(r"^\s*(?:a|an|the)\s+", "", location, flags=re.IGNORECASE)
        location = re.sub(r"^\s*(?:in|at|near|around)\s+", "", location, flags=re.IGNORECASE)
        location = location.strip(" ,.!?")
        if location and len(location) <= 100 and not any(
            term in location.lower()
            for term in ("i want", "please", "hello", "thanks", "yes", "no", "okay", "sure")
        ):
            captured["city_or_area"] = location

    return captured


def _asked_property_fields(answer: str, state: dict) -> list[str]:
    lower_answer = answer.lower()
    pending = []
    if not state.get("property_type") and (
        any(term in lower_answer for term in (
            "property type", "type of property", "residential", "commercial", "plot",
        ))
        and any(term in lower_answer for term in ("what", "which", "looking for", "interested"))
    ):
        pending.append("property_type")
    if not state.get("city_or_area") and (
        any(term in lower_answer for term in ("city", "area", "location", "where"))
        and any(term in lower_answer for term in ("what", "which", "where", "prefer", "looking"))
    ):
        pending.append("city_or_area")
    return pending


def run_turn(message: str, platform: str, user_id: str) -> str:
    """Run one full turn of the conversation and return the assistant's reply.

    This is the single function every channel (WhatsApp, Messenger, web
    chat) calls. It:
      1. loads this person's known lead info from long-term memory,
      2. lets LangGraph replay short-term (conversation) memory automatically,
      3. runs the agent -> tools -> agent loop until there's a final answer,
      4. returns just the text reply.
    """
    thread_id = build_thread_id(platform, user_id)
    lead = get_lead(user_id, platform) or {}
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = _compiled_graph.get_state(config)
    saved_state = checkpoint.values if checkpoint else {}
    pending_fields = saved_state.get("pending_fields", [])
    captured_fields = _capture_pending_answers(message, pending_fields)
    remaining_pending_fields = [
        field for field in pending_fields if field not in captured_fields
    ]
    increment_message_count(user_id, platform)

    input_state = {
        "messages": [HumanMessage(content=message)],
        "platform": platform,
        "user_id": user_id,
        "user_name": lead.get("name") or saved_state.get("user_name"),
        "user_phone": lead.get("phone") or saved_state.get("user_phone"),
        "user_email": lead.get("email") or saved_state.get("user_email"),
        "property_type": (
            captured_fields.get("property_type")
            or lead.get("property_type")
            or saved_state.get("property_type")
        ),
        "city_or_area": (
            captured_fields.get("city_or_area")
            or lead.get("city_or_area")
            or saved_state.get("city_or_area")
        ),
        "budget_range": lead.get("budget_range") or saved_state.get("budget_range"),
        "financing_method": lead.get("financing_method") or saved_state.get("financing_method"),
        "purchase_timeline": lead.get("purchase_timeline") or saved_state.get("purchase_timeline"),
        "preferred_call_time": lead.get("preferred_call_time") or saved_state.get("preferred_call_time"),
        "site_visit_requested": bool(
            lead.get("site_visit_requested", saved_state.get("site_visit_requested", False))
        ),
        "lead_stage": lead.get("stage") or saved_state.get("lead_stage", "new"),
        "lead_score": lead.get("score") if lead.get("score") is not None else saved_state.get("lead_score", 0),
        "handoff_requested": bool(
            lead.get("handoff_requested", saved_state.get("handoff_requested", False))
        ),
        "handoff_reason": lead.get("handoff_reason") or saved_state.get("handoff_reason"),
        "pending_fields": remaining_pending_fields,
    }

    result = _compiled_graph.invoke(input_state, config=config)
    final_message = result["messages"][-1]
    final_state = _compiled_graph.get_state(config).values
    answer = final_message.content
    if not isinstance(answer, str):
        answer = str(answer)
    answer = _ensure_property_questions(answer, final_state)
    next_pending_fields = _asked_property_fields(answer, final_state)
    _compiled_graph.update_state(config, {"pending_fields": next_pending_fields})

    if captured_fields and lead.get("name") and lead.get("phone"):
        lead_values = {
            "name": lead.get("name"),
            "phone": lead.get("phone"),
            "email": lead.get("email"),
            "property_type": final_state.get("property_type"),
            "city_or_area": final_state.get("city_or_area"),
            "budget_range": final_state.get("budget_range"),
            "financing_method": final_state.get("financing_method"),
            "purchase_timeline": final_state.get("purchase_timeline"),
            "preferred_call_time": final_state.get("preferred_call_time"),
            "site_visit_requested": final_state.get("site_visit_requested", False),
        }
        classification = classify_lead(platform=platform, **lead_values)
        upsert_lead(
            user_id=user_id,
            platform=platform,
            stage=classification["stage"],
            score=classification["score"],
            **captured_fields,
        )
    update_lead_summary(user_id, platform, final_state.get("messages", []))
    return answer
