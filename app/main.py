import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# app.settings loads .env and validates OPENAI_API_KEY -- import first.
from app import settings  # noqa: F401
from knowledge_base.vector_store import rebuild_vector_store
from knowledge_base import retriever as knowledge_base_retriever
from lead_intelligence.lead_schema import Lead  # noqa: F401 (kept for API docs typing)
from memory.long_term_memory import list_leads
from schema.api_schema import LeadOut
from webhook.dashboard_router import router as dashboard_router
from webhook.messenger_webhook import router as messenger_router
from webhook.web_chat_webhook import router as web_chat_router
from webhook.whatsapp_webhook import router as whatsapp_router



app = FastAPI(title="Tanveer Associates AI Assistant", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(whatsapp_router)
app.include_router(messenger_router)
app.include_router(web_chat_router)
app.include_router(dashboard_router)


@app.get("/")
def health_check():
    return {"status": "ok", "message": "Tanveer Associates AI Assistant is running."}


# ---------- Admin / ops routes ----------

@app.post("/admin/reindex")
def reindex_knowledge_base():
    """Rebuild the vector database after editing knowledge_base/company_data.py."""
    try:
        rebuild_vector_store()
        knowledge_base_retriever.refresh()
        return {"message": "Knowledge base reindexed successfully."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Reindexing failed: {e}"})


@app.get("/admin/leads", response_model=list[LeadOut])
def get_leads(stage: str | None = None):
    """List captured leads, optionally filtered by stage (new/engaged/qualified/...)."""
    return list_leads(stage=stage)


# Serve the embeddable web chat widget at /widget
app.mount("/widget", StaticFiles(directory="frontend", html=True), name="widget")
