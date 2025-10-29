# app/routers/trace.py
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from app.services.trace_logger import write_code_trace, read_traces

router = APIRouter(tags=["trace"])

class TraceIn(BaseModel):
    code: str = Field(..., description="Code généré (texte brut)")
    source: str = Field(default="manual", description="Origine (ex: self_review, chat, ui)")
    meta: Optional[Dict[str, Any]] = Field(default=None, description="Infos libres")

@router.post("/log_code")
def log_code(inp: TraceIn):
    # écriture synchrone : garantit la création du fichier immédiatement
    result = write_code_trace(inp.code, inp.source, inp.meta)
    return result

@router.get("/logs")
def logs(limit: int = 100):
    return {"items": read_traces(limit)}
