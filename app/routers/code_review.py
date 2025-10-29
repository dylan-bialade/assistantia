# app/routers/code_review.py
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict, Any
from app.models.code_change import CodeReport
from app.services.code_io import list_project_files, read_file, safe_path
from app.services.trace_logger import write_code_trace
from app.services.chat_engine import llm_local
from app.services.memory import add_many, chunk_text, search_memory

router = APIRouter(tags=["code-review"])

# ----- lecture projet -----
@router.get("/code/files")
def code_files(start: str = "app"):
    try:
        return {"items": list_project_files(start)}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get("/code/file")
def code_file(path: str = Query(..., description="Chemin relatif (ex: app/services/search.py)")):
    try:
        content = read_file(path)
        return {"path": path, "content": content}
    except Exception as e:
        raise HTTPException(400, str(e))

# ----- journalisation de rapports -----
@router.post("/report_code")
def report_code(report: CodeReport):
    payload = {
        "file_path": report.file_path,
        "objective": report.objective,
        "changes": [c.model_dump() for c in report.changes],
    }
    res = write_code_trace(
        code=f"[CODE-REPORT] {payload}",
        source="code_review/report_code",
        meta={"file": report.file_path}
    )
    return {"ok": True, **res}

# ----- proposition de patch par LLM -----
@router.post("/suggest_patch")
def suggest_patch(file_path: str, objective: str, model: Optional[str] = None):
    try:
        content = read_file(file_path)
    except Exception as e:
        raise HTTPException(400, f"Lecture impossible: {e}")

    prompt = (
        "Tu es AssistantDylan. Tu vas proposer un patch complet pour le fichier ci-dessous.\n"
        "Contraintes:\n"
        "- Retourne UNIQUEMENT le code final prêt à coller (pas d'explication).\n"
        "- Conserve l'API/structure existante au maximum.\n"
        f"- Objectif: {objective}\n\n"
        "----- DEBUT FICHIER -----\n"
        f"{content}\n"
        "----- FIN FICHIER -----\n"
        "Propose le fichier corrigé/complet :\n"
    )
    patch = llm_local(prompt)
    res = write_code_trace(
        code=patch,
        source="code_review/suggest_patch",
        meta={"file": file_path, "objective": objective, "model": model or "default"}
    )
    return {"ok": True, "patch": patch, **res}

# ======== NOUVEAU : INGESTION DU CODE EN MEMOIRE ========

@router.post("/code/ingest")
def code_ingest(
    start: str = "app",
    allow_ext: str = ".py,.js,.ts,.html,.css,.json,.md,.txt",
    chunk: int = 1000,
    overlap: int = 150,
    max_bytes: int = 300_000
):
    """
    Lit les fichiers du projet (répertoire 'start'), découpe le contenu en morceaux,
    et stocke chaque chunk dans la mémoire sémantique avec des métadonnées.
    """
    files = []
    try:
        files = list_project_files(start)
    except Exception as e:
        raise HTTPException(400, str(e))

    allow = {e.strip().lower() for e in allow_ext.split(",") if e.strip()}
    to_add: List[Dict[str, Any]] = []

    for rel in files:
        if allow and (safe_path(rel).suffix.lower() not in allow):
            continue
        try:
            txt = read_file(rel, max_bytes=max_bytes)
        except Exception:
            continue
        chunks = chunk_text(txt, chunk=chunk, overlap=overlap)
        for i, part in enumerate(chunks):
            to_add.append({
                "text": part,
                "meta": {"kind": "code", "file": rel, "chunk": i, "total_chunks": len(chunks)}
            })

    n = add_many(to_add)
    return {"ok": True, "indexed_chunks": n, "files_scanned": len(files)}

@router.get("/code/search")
def code_search(q: str, k: int = 8):
    """
    Recherche sémantique dans la mémoire limitée aux items de type 'code'.
    """
    hits = search_memory(q, k=k, filter_meta={"kind": "code"})
    # Raccourci d'affichage
    out = []
    for h in hits:
        meta = h.get("meta") or {}
        out.append({
            "score": round(h["score"], 4),
            "file": meta.get("file"),
            "chunk": meta.get("chunk"),
            "preview": h["text"][:300]
        })
    return {"query": q, "results": out}
