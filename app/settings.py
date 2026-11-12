"""Centralized environment configuration. Import from here, not os.getenv() everywhere."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root before anything else reads an env var.
# override=True ensures .env always wins over stale system-level env vars.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    sys.exit("ERROR: OPENAI_API_KEY is missing. Add it to your .env file before starting the app.")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# PostgreSQL -- used for both short-term (conversation) and long-term
# (leads/CRM) memory. See memory/short_term_memory.py and
# memory/long_term_memory.py.
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tanveer_associates"
)

# Meta (WhatsApp Cloud API + Messenger) credentials
META_VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_secret_verify_2024")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

MESSENGER_PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
if not MESSENGER_PAGE_ACCESS_TOKEN:
    import warnings
    warnings.warn("PAGE_ACCESS_TOKEN is not set — Messenger replies will fail.", stacklevel=1)

# Optional: notify a human when escalate_to_human fires (Slack incoming webhook URL etc).
HANDOFF_NOTIFY_WEBHOOK_URL = os.getenv("HANDOFF_NOTIFY_WEBHOOK_URL", "")

# Set to "true" in .env to enable email lead notifications.
# Off by default until the email pipeline is fully tested.
REPORTING_ENABLED = os.getenv("REPORTING_ENABLED", "false").lower() == "true"
