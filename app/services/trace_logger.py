# app/services/trace_logger.py
from pathlib import Path
from datetime import datetime
import json
from typing import Optional, Dict, Any, List

LOG_DIR = Path("data/logs")
LOG_FILE = LOG_DIR / "generated_code_traces.jsonl"

def _ensure_dirs():
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"Impossible de créer {LOG_DIR}: {e}")

def write_code_trace(code: str, source: str = "self_review", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Écrit immédiatement (synchrone) une ligne JSON dans generated_code_traces.jsonl.
    Retourne le chemin du fichier pour vérification.
    """
    _ensure_dirs()
    rec = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source": source,
        "meta": meta or {},
        "code": code,
    }
    line = json.dumps(rec, ensure_ascii=False)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return {"ok": True, "path": str(LOG_FILE), "bytes": len(line)}

def read_traces(limit: int = 100) -> List[Dict[str, Any]]:
    _ensure_dirs()
    if not LOG_FILE.exists():
        return []
    out: List[Dict[str, Any]] = []
    with LOG_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out[-limit:]
