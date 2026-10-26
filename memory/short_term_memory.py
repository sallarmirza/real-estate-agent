"""Short-term (per-conversation) memory, backed by PostgreSQL.

LangGraph persists the *entire* graph state (messages + our custom
fields like lead stage) between calls, keyed by a "thread_id". As long
as we pass the same thread_id for the same user, the agent automatically
remembers the whole conversation -- we never manually re-send history.

Uses the same Postgres database as long_term_memory.py (a different set
of tables, created and managed by LangGraph itself via .setup()).
"""

import os
from typing import Optional

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv(
    "DATABASE_URL"
)

_pool: Optional[ConnectionPool] = None
_checkpointer: Optional[PostgresSaver] = None


def get_checkpointer() -> PostgresSaver:
    """Return a process-wide PostgresSaver checkpointer (created on first use)."""
    global _pool, _checkpointer
    if _checkpointer is None:
        # autocommit=True is required by PostgresSaver (it runs its own
        # transactions internally for checkpoint writes).
        _pool = ConnectionPool(
            DATABASE_URL, min_size=1, max_size=10, open=True,
            kwargs={"autocommit": True, "row_factory": None},
        )
        _checkpointer = PostgresSaver(_pool)
        _checkpointer.setup()  # creates LangGraph's checkpoint tables if missing
    return _checkpointer


def build_thread_id(platform: str, user_id: str) -> str:
    """Build the LangGraph thread_id that scopes memory to one user on one channel.

    Using "platform:user_id" means the same person messaging on WhatsApp and
    on Messenger is treated as two separate conversations (their identifiers
    are different anyway), while every message from the same WhatsApp number
    always resumes the same thread.
    """
    return f"{platform}:{user_id}"
