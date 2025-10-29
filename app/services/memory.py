# app/services/memory.py
"""
File-based lightweight memory with fuzzy search.

- Stores items as JSONL in data/memory/memory.jsonl
- search_memory supports both `k=` and `top_k=` (backwards compatible)
- Returns hits as strings (safe for "\n".join(...) in chat_engine)
- add_many / add_many_unique accept either strings OR dicts of the form:
  {"text": "...", "meta": {...}}
"""

from __future__ import annotations

import os
import json
import math
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

DATA_DIR = Path("data") / "memory"
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEM_FILE = DATA_DIR / "memory.jsonl"

_lock = threading.RLock()


# -----------------------------
# Utilities
# -----------------------------
def _normalize_text(s: Any) -> str:
    """Normalize text; non-strings become empty string (caller should extract text first)."""
    if not isinstance(s, str):
        return ""
    return " ".join((s or "").strip().split())


def _tokenize(s: str) -> List[str]:
    s = s.lower()
    out: List[str] = []
    buff: List[str] = []
    for ch in s:
        if ch.isalnum():
            buff.append(ch)
        else:
            if buff:
                out.append("".join(buff))
                buff = []
    if buff:
        out.append("".join(buff))
    return out


def _tf(text: str) -> Dict[str, float]:
    toks = _tokenize(text)
    if not toks:
        return {}
    total = float(len(toks))
    counts: Dict[str, float] = {}
    for t in toks:
        counts[t] = counts.get(t, 0.0) + 1.0
    for k in list(counts):
        counts[k] = counts[k] / total
    return counts


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    for k, va in a.items():
        vb = b.get(k)
        if vb:
            dot += va * vb
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _load_all() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not MEM_FILE.exists():
        return items
    with _lock:
        with MEM_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    return items


def _append(item: Dict[str, Any]) -> None:
    with _lock:
        with MEM_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _rewrite(all_items: List[Dict[str, Any]]) -> None:
    with _lock:
        tmp = MEM_FILE.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for it in all_items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        tmp.replace(MEM_FILE)


def _extract_text_meta(obj: Union[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """
    Accepts:
      - str -> returns (text, {})
      - dict -> expects {"text": str, "meta": dict?}
    """
    if isinstance(obj, str):
        return _normalize_text(obj), {}
    if isinstance(obj, dict):
        text = _normalize_text(obj.get("text"))
        meta = obj.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {"_bad_meta": True}
        return text, meta
    # unsupported type
    return "", {}


# -----------------------------
# Public API
# -----------------------------
def chunk_text(text: str, chunk: int = 1000, overlap: int = 150) -> List[str]:
    text = _normalize_text(text)
    if not text:
        return []
    if chunk <= 0:
        return [text]
    out: List[str] = []
    i = 0
    n = len(text)
    step = max(1, chunk - max(0, overlap))
    while i < n:
        out.append(text[i : i + chunk])
        i += step
    return out


def save_text_memory(
    text: Union[str, Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Save one entry to memory.jsonl.
    Accepts str or {"text": "...", "meta": {...}}.
    If `text` is a dict, its meta is merged with `meta` (explicit param wins).
    """
    if isinstance(text, dict):
        t, m = _extract_text_meta(text)
        meta_final = {**(m or {}), **(meta or {})} if meta else (m or {})
        item: Dict[str, Any] = {
            "type": "text",
            "text": t,
            "meta": meta_final,
        }
    else:
        t = _normalize_text(text)
        item = {
            "type": "text",
            "text": t,
            "meta": meta or {},
        }
    _append(item)
    return item


# Back-compat alias (some modules still import these)
add_to_memory = save_text_memory


def add_many(docs: Iterable[Union[str, Dict[str, Any]]], base_meta: Optional[Dict[str, Any]] = None) -> int:
    count = 0
    for d in docs:
        t, m = _extract_text_meta(d)
        if not t:
            continue
        meta_final = {**(m or {}), **(base_meta or {})} if base_meta else (m or {})
        save_text_memory({"text": t, "meta": meta_final})
        count += 1
    return count


def add_many_unique(
    docs: Iterable[Union[str, Dict[str, Any]]],
    base_meta: Optional[Dict[str, Any]] = None,
    dedup_on_text: bool = True,
) -> int:
    """
    Add texts (or text dicts) if not already present (very naive dedup).
    """
    existing = _load_all()
    seen = set()
    if dedup_on_text:
        for it in existing:
            if it.get("type") == "text":
                seen.add(_normalize_text(it.get("text")))

    count = 0
    for d in docs:
        t, m = _extract_text_meta(d)
        if not t:
            continue
        if dedup_on_text and t in seen:
            continue
        meta_final = {**(m or {}), **(base_meta or {})} if base_meta else (m or {})
        save_text_memory({"text": t, "meta": meta_final})
        seen.add(t)
        count += 1
    return count


def remove_by_meta(match: Dict[str, Any]) -> int:
    """
    Remove items whose meta contains all key/values in `match`.
    Returns number removed.
    """
    all_items = _load_all()
    keep: List[Dict[str, Any]] = []
    removed = 0
    for it in all_items:
        meta = it.get("meta") or {}
        ok = True
        for k, v in match.items():
            if meta.get(k) != v:
                ok = False
                break
        if ok:
            removed += 1
        else:
            keep.append(it)
    if removed:
        _rewrite(keep)
    return removed


def search_memory(
    query: str,
    k: Optional[int] = None,
    top_k: Optional[int] = None,
    filter_meta: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    Returns a list of **strings** (hit texts), so chat_engine can do "\n".join(hits).
    Accepts either `k=` or `top_k=` for backwards compatibility.
    """
    if k is None and top_k is None:
        top_k = 5
    if top_k is None:
        top_k = k or 5

    query = _normalize_text(query)
    q_vec = _tf(query)
    items = _load_all()

    scored: List[Tuple[float, str]] = []
    for it in items:
        if filter_meta:
            meta = it.get("meta") or {}
            ok = True
            for fk, fv in filter_meta.items():
                if meta.get(fk) != fv:
                    ok = False
                    break
            if not ok:
                continue

        text = _normalize_text(it.get("text"))
        if not text:
            continue
        s = _cosine(q_vec, _tf(text))
        if s <= 0.0:
            continue
        scored.append((s, text))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[: max(1, int(top_k))]]


# -------- code proposals (for self_update) ----------
def save_proposal(patch: str, objective: str) -> Dict[str, Any]:
    """
    Store a generated patch so we can retrieve / audit later.
    """
    item = {
        "type": "proposal",
        "text": _normalize_text(patch),
        "meta": {"kind": "patch", "objective": objective},
    }
    _append(item)
    return item


def load_all_raw() -> List[Dict[str, Any]]:
    """For debug or external tools."""
    return _load_all()

# --- Compat ALIAS pour anciens imports ---

def add_text(text: Union[str, Dict[str, Any]], meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Alias rétro-compat pour anciens modules (équivalent de save_text_memory)."""
    return save_text_memory(text, meta)

def search_memory_dict(
    query: str,
    k: Optional[int] = None,
    top_k: Optional[int] = None,
    filter_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Variante qui renvoie des dicts {text, score} pour les modules qui en ont besoin.
    Basée sur ta logique actuelle (qui renvoie des strings).
    """
    if k is None and top_k is None:
        top_k = 5
    if top_k is None:
        top_k = k or 5

    # On réutilise les helpers internes
    query_norm = _normalize_text(query)
    q_vec = _tf(query_norm)
    items = _load_all()

    scored = []
    for it in items:
        if filter_meta:
            meta = it.get("meta") or {}
            ok = True
            for fk, fv in filter_meta.items():
                if meta.get(fk) != fv:
                    ok = False
                    break
            if not ok:
                continue

        text = _normalize_text(it.get("text"))
        if not text:
            continue
        s = _cosine(q_vec, _tf(text))
        if s <= 0.0:
            continue
        scored.append({"text": text, "score": s, "meta": it.get("meta", {})})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[: max(1, int(top_k))]
