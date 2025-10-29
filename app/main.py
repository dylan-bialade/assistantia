import os
from fastapi import FastAPI
from app.routers.deep_search import router as search_router
from app.routers.chat import router as chat_router
from app.routers.self_update_router import router as self_router
from app.routers.code_review import router as code_review_router
from app.routers.trace import router as trace_router
from app.routers.patch_router import router as patch_router
from app.services.startup_indexer import startup_ingest_if_changed
from app.routers.persona import router as persona_router


app = FastAPI(title="Assistant IA évolutif (GPU) de Dylan")

# Routers
app.include_router(persona_router)
app.include_router(patch_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(self_router)
app.include_router(code_review_router)
app.include_router(trace_router)

_started_once = False

@app.on_event("startup")
def _auto_ingest_on_start():
    global _started_once
    if _started_once:
        return            # garde-fou si import double
    _started_once = True

    if os.getenv("ANDY_AUTO_INGEST", "1") != "1":
        print("[startup] Auto-ingest désactivé (ANDY_AUTO_INGEST=0).")
        return

    res = startup_ingest_if_changed(
        start="app",
        allow_ext=(".py",".js",".ts",".html",".css",".json",".md",".txt"),
        chunk=1000,
        overlap=150,
        max_bytes=300_000,
        verbose=True
    )
    print("[startup] Ingest:", res)

@app.get("/")
def root():
    return {
        "ok": True,
        "msg": "Assistant IA (GPU) — prêt.",
        "routes": [r.path for r in app.router.routes],
        "ui": ["/ui", "/chat_ui", "/profile", "/self_review"]
    }
