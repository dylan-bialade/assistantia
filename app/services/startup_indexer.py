# app/services/startup_indexer.py
from __future__ import annotations
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple, Iterable
from datetime import datetime

from app.services.memory import (
    chunk_text,
    add_many_unique,
    remove_by_meta,   # utilisé pour nettoyer les anciennes entrées si besoin
)

DATA_ROOT = Path("data")
MEM_DIR = DATA_ROOT / "memory"
MEM_DIR.mkdir(parents=True, exist_ok=True)

INDEX_PATH = MEM_DIR / "code_index.json"

def _hash_bytes(b: bytes) -> str:
    h = hashlib.sha1()
    h.update(b)
    return h.hexdigest()

def _hash_text(s: str) -> str:
    return _hash_bytes(s.encode("utf-8", errors="ignore"))

def _load_index() -> Dict[str, Dict[str, Any]]:
    """
    Lit l'index JSON et normalise toutes les clés en POSIX (anti \ vs /).
    Si l'ancien fichier contenait des clés en backslash, on les convertit ici.
    """
    if not INDEX_PATH.exists():
        return {}

    try:
        with INDEX_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}

    if not isinstance(raw, dict):
        return {}

    migrated: Dict[str, Dict[str, Any]] = {}
    for k, v in raw.items():
        # normalise en / (POSIX)
        k_posix = k.replace("\\", "/")
        # si collision improbable, on garde la dernière (ou on pourrait fusionner)
        migrated[k_posix] = v

    # si on a changé quelque chose, réécrit l’index migré une fois
    if set(migrated.keys()) != set(raw.keys()):
        try:
            with INDEX_PATH.open("w", encoding="utf-8") as f:
                json.dump(migrated, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return migrated


def _save_index(idx: Dict[str, Dict[str, Any]]) -> None:
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

def _iter_files(
    start: Path,
    allow_ext: Tuple[str, ...]
) -> Iterable[Path]:
    for p in start.rglob("*"):
        if p.is_file() and p.suffix.lower() in allow_ext:
            yield p

def _scan_dir(
    start: str | Path,
    allow_ext: Tuple[str, ...] = (".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".txt"),
    max_bytes: int = 300_000,
) -> Dict[str, Dict[str, Any]]:
    """
    Retourne un nouvel index: { path_posix: {hash, size, mtime} }
    - paths normalisés en POSIX (anti flapping Windows \ vs /)
    - hash calculé sur le contenu tronqué à max_bytes (suffisant pour détecter des modifs)
    """
    start_p = Path(start)
    out: Dict[str, Dict[str, Any]] = {}
    for p in _iter_files(start_p, allow_ext):
        try:
            b = p.read_bytes()
        except Exception:
            continue
        b_cut = b[:max_bytes]
        h = _hash_bytes(b_cut)
        stat = p.stat()
        k = p.as_posix()  # clé POSIX
        out[k] = {
            "hash": h,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        }
    return out

def _diff_index(old: Dict[str, Dict[str, Any]], new: Dict[str, Dict[str, Any]]):
    """
    Calcule added/removed/changed entre deux index (clés = chemins POSIX).
    """
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)

    changed: List[str] = []
    common = old_keys & new_keys
    for k in common:
        if old[k].get("hash") != new[k].get("hash"):
            changed.append(k)

    return {
        "added": added,
        "removed": removed,
        "changed": sorted(changed),
    }

def _make_memory_items_for_file(path_posix: str, text: str) -> List[Dict[str, Any]]:
    """
    Transforme un fichier texte en items mémoire chunkés.
    """
    items: List[Dict[str, Any]] = []
    chunks = chunk_text(text, chunk=1000, overlap=150)
    for ch in chunks:
        items.append({
            "text": ch,
            "meta": {
                "source": "code_index",
                "path": path_posix
            }
        })
    return items

def startup_ingest_if_changed(
    start: str | Path = "app",
    allow_ext: Tuple[str, ...] = (".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".txt"),
    chunk: int = 1000,
    overlap: int = 150,
    max_bytes: int = 300_000,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    À chaque démarrage:
      - scanne 'start' et calcule un nouvel index (chemins POSIX + hash contenu)
      - compare avec l'ancien index
      - pour les fichiers 'added' et 'changed', (re)ingeste leur contenu en mémoire
      - pour les 'removed', nettoie la mémoire correspondante
      - sauvegarde l'index
    Retourne {added, removed, changed, written}
    """
    start_p = Path(start)

    # 1) Charger index précédent
    old_index = _load_index()

    # 2) Scanner répertoire
    new_index = _scan_dir(start_p, allow_ext=allow_ext, max_bytes=max_bytes)
    if verbose:
        print(f"[startup_indexer] scan_dir: {len(new_index)} fichiers")

    # 3) Diff
    diff = _diff_index(old_index, new_index)
    added = diff["added"]
    removed = diff["removed"]
    changed = diff["changed"]

    # 4) Mise à jour mémoire
    written = 0

    # Nettoyage des anciens morceaux associés aux fichiers supprimés
    if removed:
        # supprime tous les morceaux dont meta.source='code_index' ET meta.path=path_posix
        count = 0
        for rp in removed:
            count += remove_by_meta(source="code_index", where=rp, target="free_text")
        if verbose:
            print(f"[startup_indexer] memory cleanup: removed {count} old code_index entries")

    # Ajout / Mise à jour des contenus
    to_write: List[Dict[str, Any]] = []
    for path_posix in (added + changed):
        try:
            text = Path(path_posix).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            # En cas de lecture depuis un chemin POSIX, on recompose depuis Windows Path
            p = Path(path_posix.replace("/", "\\"))
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
        # re-chunk avec les paramètres donnés
        chunks = chunk_text(text, chunk=chunk, overlap=overlap)
        for ch in chunks:
            to_write.append({
                "text": ch,
                "meta": {"source": "code_index", "path": path_posix}
            })

    if to_write:
        written = add_many_unique(to_write)
        if verbose:
            print(f"[startup_indexer] wrote {written} memory items; index will be saved to {INDEX_PATH}")

    # 5) Sauvegarder le nouvel index
    _save_index(new_index)

    out = {
        "added": added,
        "removed": removed,
        "changed": changed,
        "written": written,
    }
    if verbose:
        print("[startup] Ingest:", out)
    return out
