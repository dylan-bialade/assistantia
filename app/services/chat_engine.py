# app/services/chat_engine.py
from __future__ import annotations
import json
import os
import re
import requests
from typing import List, Tuple, Optional, Dict

# Mémoire locale
from app.services.memory import add_text, search_memory  # assure-toi que ces fonctions existent (sinon renomme vers tes helpers)

# === Config Ollama ===
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate"
MODEL_NAME = os.getenv("OLLAMA_MODEL", "phi3")

SYSTEM_CORE = (
    "Tu es Andy, une IA locale créée par Dylan. "
    "Réponds avec précision, brièveté et pragmatisme. "
    "Toujours respecter la langue de l’utilisateur. "
    "Toujours respecter la stack/technologie demandée. "
    "Si l’utilisateur parle de C#/.NET, réponds en C# (pas Python). "
    "Si l’utilisateur parle de Python, réponds en Python, etc. "
    "Si l’intention ou la stack n’est pas claire, pose 1 question de clarification courte."
)

# ------------------------
# Heuristiques légères
# ------------------------

LANG_PATTERNS = [
    ("fr", re.compile(r"[àâçéèêëîïôûùüÿœæÀÂÇÉÈÊËÎÏÔÛÙÜŸŒÆ]|(?:\b(le|la|les|un|une|des|pourquoi|comment|bonjour)\b)", re.I)),
    ("en", re.compile(r"\b(the|a|an|why|how|please|hello)\b", re.I)),
]

TECH_HINTS = {
    "csharp": re.compile(r"\b(c#|csharp|\.net|asp\.net|ef core|blazor|maui)\b", re.I),
    "python": re.compile(r"\b(python|fastapi|flask|pandas|django)\b", re.I),
    "java": re.compile(r"\b(java|spring|spring boot|maven|gradle)\b", re.I),
    "js": re.compile(r"\b(javascript|node\.js|node|react|next\.js|svelte|vue)\b", re.I),
    "php": re.compile(r"\b(php|laravel|symfony|composer)\b", re.I),
}

CODE_FENCE = {
    "csharp": "csharp",
    "python": "python",
    "java": "java",
    "js": "javascript",
    "php": "php"
}

def detect_lang(text: str, default: str = "fr") -> str:
    t = (text or "").strip()
    for lang, pat in LANG_PATTERNS:
        if pat.search(t):
            return lang
    # fallback: si beaucoup d’accents → fr
    if re.search(r"[àâçéèêëîïôûùüÿœæ]", t, re.I):
        return "fr"
    return default

def detect_tech(text: str) -> Optional[str]:
    t = (text or "").lower()
    for tech, pat in TECH_HINTS.items():
        if pat.search(t):
            return tech
    return None

def enforce_format_instructions(lang: str, tech: Optional[str]) -> str:
    # instructions strictes pour langue + stack
    lines = []
    if lang == "fr":
        lines.append("LANGUE: Français uniquement.")
    else:
        lines.append("LANGUAGE: English only.")
    if tech:
        if lang == "fr":
            lines.append(f"STACK: {tech}. Respecte strictement cette stack.")
            lines.append("Quand tu fournis du code, utilise des blocs ```lang appropriés.")
        else:
            lines.append(f"STACK: {tech}. Strictly respect this stack.")
            lines.append("When providing code, use proper ```lang fenced blocks.")
    else:
        if lang == "fr":
            lines.append("STACK: Déduis-la du message. Si ambigu, pose 1 question de clarification.")
        else:
            lines.append("STACK: Infer it from the message. If ambiguous, ask 1 clarification question.")

    # mapping des fences
    if tech and tech in CODE_FENCE:
        fence = CODE_FENCE[tech]
        if lang == "fr":
            lines.append(f"Quand tu fournis du code, utilise ```{fence} … ```.")
        else:
            lines.append(f"When you provide code, use ```{fence} … ```.")

    # style concis
    if lang == "fr":
        lines.append("Style: concis, structuré, étapes claires, pas de blabla.")
    else:
        lines.append("Style: concise, structured, clear steps, no fluff.")
    return "\n".join(lines)

def llm_local(prompt: str) -> str:
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": MODEL_NAME, "prompt": prompt, "stream": False},
            timeout=180
        )
        r.raise_for_status()
        try:
            j = r.json()
            return j.get("response") or ""
        except json.JSONDecodeError:
            # fallback NDJSON
            r = requests.post(OLLAMA_URL, json={"model": MODEL_NAME, "prompt": prompt}, stream=True, timeout=180)
            r.raise_for_status()
            chunks: List[str] = []
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    chunks.append(obj.get("response", ""))
                except Exception:
                    pass
            return "".join(chunks).strip()
    except Exception as e:
        return f"(LLM local indisponible: {e})"

def violates_lang(reply: str, lang: str) -> bool:
    if lang == "fr":
        # si quasiment pas de mots FR et beaucoup de patterns EN → violation
        if re.search(r"\b(the|a|an|please|thanks|hello)\b", reply, re.I) and not re.search(r"\b(le|la|les|un|une|bonjour|merci)\b", reply, re.I):
            return True
    else:
        # basique: s’il y a beaucoup d’accents/balises FR
        if re.search(r"\b(le|la|les|un|une|bonjour|merci)\b", reply, re.I):
            return True
    return False

def violates_tech(reply: str, tech: Optional[str]) -> bool:
    if not tech:
        return False
    # si l’utilisateur veut C#, mais on voit "def " typique Python → violation
    if tech == "csharp":
        if "```python" in reply.lower() or re.search(r"\bdef\s+\w+\(", reply):
            return True
    if tech == "python":
        if "```csharp" in reply.lower() or re.search(r"\bpublic\s+(class|static|void)\b", reply):
            return True
    if tech == "java":
        if "```python" in reply.lower() or "```csharp" in reply.lower():
            return True
    if tech == "php":
        if "```python" in reply.lower() or "```csharp" in reply.lower():
            return True
    if tech == "js":
        if "```python" in reply.lower() or "```csharp" in reply.lower():
            return True
    return False

def build_prompt(user_msg: str, memory_snippets: List[str]) -> str:
    lang = detect_lang(user_msg)
    tech = detect_tech(user_msg)

    header = SYSTEM_CORE + "\n" + enforce_format_instructions(lang, tech)
    memory = "\n--- Mémoire ---\n" + "\n".join(memory_snippets) if memory_snippets else ""
    user = f"\n--- Utilisateur ({lang}) ---\n{user_msg}\n"

    # few-shot simple pour ancrer C#
    if tech == "csharp":
        shot = (
            "\n--- Exemples ---\n"
            "Q: Crée un contrôleur ASP.NET Core minimal pour exposer GET /ping\n"
            "R:\n"
            "```csharp\n"
            "using Microsoft.AspNetCore.Mvc;\n"
            "\n"
            "[ApiController]\n"
            "[Route(\"api/[controller]\")]\n"
            "public class PingController : ControllerBase {\n"
            "    [HttpGet(\"/ping\")]\n"
            "    public IActionResult Ping() => Ok(new { pong = true });\n"
            "}\n"
            "```\n"
        )
    else:
        shot = ""

    return header + memory + user + shot + "\n--- Réponse ---\n"

def chat_with_user(message: str) -> str:
    # 1) Récupère de la mémoire pertinente (texte uniquement)
    hits = search_memory(message)
    memory_texts = []
    for h in (hits or []):
        if isinstance(h, dict):
            t = (h.get("text") or "").strip()
            if t:
                memory_texts.append(t)
        elif isinstance(h, str):
            t = h.strip()
            if t:
                memory_texts.append(t)

    prompt = build_prompt(message, memory_texts)
    first = llm_local(prompt)

    # 2) Guardrail : vérifier langue + stack, sinon on redemande une réécriture conforme
    lang = detect_lang(message)
    tech = detect_tech(message)

    if violates_lang(first, lang) or violates_tech(first, tech):
        correction_inst = (
            f"Réécris la réponse STRICTEMENT dans la bonne langue ({'français' if lang=='fr' else 'english'})"
            f"{f' et avec la bonne stack ({tech})' if tech else ''}. "
            "Fournis du code uniquement dans la stack demandée. Rien d’autre."
        )
        second = llm_local(prompt + "\n\n[CONTRAINTE SUPPLÉMENTAIRE]\n" + correction_inst)
        if second and not violates_lang(second, lang) and not violates_tech(second, tech):
            reply = second
        else:
            reply = first  # on garde la 1ère si la 2e n’est pas meilleure
    else:
        reply = first

    # 3) Sauvegarde un petit résumé utilisateur/réponse en mémoire
    try:
        add_text(f"USER: {message}\nASSISTANT: {reply[:1200]}")
    except Exception:
        pass

    return reply
