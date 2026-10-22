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

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from conversation_layer.state import AgentState
from conversation_layer.system_prompt import (
    build_system_prompt,
    clean_reply,
    ensure_lead_follow_up,
)
from conversation_layer.tools import TOOLS
from memory.long_term_memory import get_lead, increment_message_count
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
    if not response.tool_calls:
        user_message = next(
            (
                message.content
                for message in reversed(state["messages"])
                if isinstance(message, HumanMessage) and isinstance(message.content, str)
            ),
            "",
        )
        reply = clean_reply(response.content)
        response = response.model_copy(
            update={
                "content": ensure_lead_follow_up(reply, state, user_message),
            }
        )
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
    increment_message_count(user_id, platform)

    config = {"configurable": {"thread_id": thread_id}}

    # These fields only need to be provided on the *first* turn of a thread;
    # LangGraph keeps using the checkpointed values on every turn after that.
    # Passing them every time is harmless -- they only take effect via
    # tool-issued Command updates or on first creation of the thread.
    input_state = {
        "messages": [HumanMessage(content=message)],
        "platform": platform,
        "user_id": user_id,
        "user_name": lead.get("name"),
        "user_phone": lead.get("phone"),
        "user_email": lead.get("email"),
        "property_type": lead.get("property_type"),
        "city_or_area": lead.get("city_or_area"),
        "budget_range": lead.get("budget_range"),
        "financing_method": lead.get("financing_method"),
        "purchase_timeline": lead.get("purchase_timeline"),
        "preferred_call_time": lead.get("preferred_call_time"),
        "site_visit_requested": bool(lead.get("site_visit_requested", False)),
        "site_visit_answered": bool(lead.get("site_visit_answered", False)),
        "lead_stage": lead.get("stage", "new"),
        "lead_score": lead.get("score", 0),
        "handoff_requested": bool(lead.get("handoff_requested", False)),
        "handoff_reason": lead.get("handoff_reason"),
    }

    result = _compiled_graph.invoke(input_state, config=config)
    final_message = result["messages"][-1]
    return final_message.content
