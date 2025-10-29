# app/services/code_io.py
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # racine: dossier assistantia/
ALLOW_EXT = {".py", ".txt", ".md", ".json", ".html", ".js", ".css"}

def safe_path(rel_path: str) -> Path:
    """Retourne un Path sécurisé, empêchant la sortie de la racine projet."""
    p = (PROJECT_ROOT / rel_path).resolve()
    if PROJECT_ROOT not in p.parents and p != PROJECT_ROOT:
        raise ValueError("Chemin en dehors du projet interdit.")
    return p

def list_project_files(start: str = "app") -> List[str]:
    base = safe_path(start)
    out: List[str] = []
    for p in base.rglob("*"):
        if p.is_file() and p.suffix.lower() in ALLOW_EXT:
            out.append(str(p.relative_to(PROJECT_ROOT)))
    return sorted(out)

def read_file(rel_path: str, max_bytes: int = 300_000) -> str:
    p = safe_path(rel_path)
    data = p.read_bytes()
    if len(data) > max_bytes:
        raise ValueError("Fichier trop volumineux pour l'aperçu.")
    return data.decode("utf-8", errors="replace")
