# app/routers/feedback.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.services.nn_personalizer import FEEDBACK_FILE, personalizer_train_from_feedback

router = APIRouter(prefix="", tags=["feedback"])

@router.post("/feedback")
def post_feedback(
    url: str = Body(...),
    title: Optional[str] = Body(None),
    summary: Optional[str] = Body(None),
    query: Optional[str] = Body(None),
    label: str = Body(..., embed=False),  # "like" / "dislike"
    extra: Optional[Dict[str, Any]] = Body(None),
):
    """Enregistre un feedback utilisateur."""
    obj = {
        "url": url,
        "title": title,
        "summary": summary,
        "query": query,
        "label": label,
        "meta": extra or {},
    }
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return {"ok": True, "detail": "feedback stored"}

@router.post("/feedback/train")
def train_from_feedback(limit: Optional[int] = Body(None), epochs: Optional[int] = Body(2)):
    """Entraîne/re-entraine le réseau sur les feedbacks stockés."""
    res = personalizer_train_from_feedback(limit=limit, epochs=epochs or 2)
    return res

@router.get("/feedback/stats")
def feedback_stats():
    """Stats basiques."""
    total = 0
    likes = 0
    if FEEDBACK_FILE.exists():
        with FEEDBACK_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                total += 1
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                lab = obj.get("label")
                if isinstance(lab, str) and lab.lower() in ("like", "up", "good", "1", "👍"):
                    likes += 1
                elif isinstance(lab, (int, float)) and float(lab) >= 0.5:
                    likes += 1
    return {"total": total, "likes": likes, "like_ratio": (likes / total) if total else 0.0}
