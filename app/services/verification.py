# app/services/verification.py
import json
import re
import ast
from typing import Dict, Any, Optional, Tuple
from app.services.chat_engine import llm_local

VERIFIER_SYSTEM = """
Tu es un vérificateur de revues de code.
But: dire si le code proposé atteint l'objectif sans casser l'existant.
Réponds UNIQUEMENT en JSON avec les clés:
- pass (bool)
- score (0..100)
- reasons (array[string])
- risks (array[string])
- suggested_tests (array[string])
- summary (string)
"""

def _extract_fenced_code(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extrait le premier bloc de code balisé ```lang\n...\n``` s'il existe.
    Retourne (lang, code) ou (None, None).
    """
    m = re.search(r"```(\w+)?\s*\n(.*?)```", text, flags=re.S|re.M)
    if not m:
        return None, None
    lang = (m.group(1) or "").strip().lower()
    code = m.group(2)
    return lang, code

def _local_syntax_check(lang: Optional[str], code: Optional[str]) -> Dict[str, Any]:
    """
    Vérifications locales non bloquantes : syntaxe Python/JSON/JS simple.
    """
    if not code:
        return {"syntax_ok": None, "syntax_error": None, "lang": lang}

    if lang in ("python", "py"):
        try:
            ast.parse(code)
            return {"syntax_ok": True, "syntax_error": None, "lang": lang}
        except SyntaxError as e:
            return {"syntax_ok": False, "syntax_error": str(e), "lang": lang}

    if lang == "json":
        try:
            json.loads(code)
            return {"syntax_ok": True, "syntax_error": None, "lang": lang}
        except Exception as e:
            return {"syntax_ok": False, "syntax_error": str(e), "lang": lang}

    # Basique pour JS/TS: on ne parse pas, on note juste non vérifié
    if lang in ("js", "javascript", "ts", "typescript"):
        return {"syntax_ok": None, "syntax_error": None, "lang": lang}

    return {"syntax_ok": None, "syntax_error": None, "lang": lang}

def build_verifier_prompt(objective: str, proposal: str, context: Optional[str] = None) -> str:
    ctx = f"\nContexte:\n{context}\n" if context else ""
    return (
        f"{VERIFIER_SYSTEM}\n"
        f"Objectif:\n{objective}\n"
        f"{ctx}"
        f"Proposition:\n{proposal}\n\n"
        "Réponds en JSON uniquement."
    )

def verify_patch(objective: str, proposal: str, context: Optional[str] = None) -> Dict[str, Any]:
    """
    1) Vérifie localement la syntaxe du bloc de code (si présent).
    2) Demande un verdict structuré au LLM local.
    """
    lang, code = _extract_fenced_code(proposal)
    syntax = _local_syntax_check(lang, code)

    prompt = build_verifier_prompt(objective, proposal, context=context)
    raw = llm_local(prompt)

    try:
        verdict = json.loads(raw)
        # garde au moins les clés attendues
        for k in ["pass", "score", "reasons", "risks", "suggested_tests", "summary"]:
            verdict.setdefault(k, None)
    except Exception:
        verdict = {
            "pass": False,
            "score": 0,
            "reasons": ["Réponse non-JSON du LLM."],
            "risks": [],
            "suggested_tests": [],
            "summary": (raw or "").strip()[:2000],
        }

    return {
        "syntax": syntax,   # ex: {"syntax_ok": True/False/None, "syntax_error": "...", "lang": "python"}
        "verdict": verdict  # JSON du modèle (pass/score/reasons/risks/suggested_tests/summary)
    }
