import json
from pathlib import Path
from typing import Dict, Any

DATA_DIR = Path("data/persona")
DATA_DIR.mkdir(parents=True, exist_ok=True)
PERSONA_FILE = DATA_DIR / "persona.json"

DEFAULT_PERSONA: Dict[str, Any] = {
    "name": "Andy",
    "creator": "Dylan Bialade",
    "mission": "Aider Dylan: recherche web personnalisée, génération et auto-amélioration de code, explications claires.",
    "style": {
        "tone": "friendly",
        "verbosity": "normal",   # "terse" | "normal" | "detailed"
        "simplicity": "simple",  # "simple" | "technical"
        "emoji": True
    },
    "knowledge": {
        "about_self": [
            "Je suis un assistant IA local surnommé Andy.",
            "Je tourne sur la machine de Dylan et j’utilise le GPU si dispo.",
            "Je peux mémoriser des préférences et des connaissances utiles."
        ],
        "about_creator": [
            "Mon créateur est Dylan (bachelor).",
            "Je dois prioriser l’aide sur ses projets (Symfony, React/Native, Android, DevOps,Hacking)."
        ]
    }
}

def _load() -> Dict[str, Any]:
    if PERSONA_FILE.exists():
        try:
            return json.loads(PERSONA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    save(DEFAULT_PERSONA)
    return DEFAULT_PERSONA

def save(data: Dict[str, Any]) -> None:
    PERSONA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_persona() -> Dict[str, Any]:
    return _load()

def update_persona(patch: Dict[str, Any]) -> Dict[str, Any]:
    persona = _load()
    # merge superficiel (clé par clé)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(persona.get(k), dict):
            persona[k].update(v)
        else:
            persona[k] = v
    save(persona)
    return persona

def set_style(tone: str | None = None, verbosity: str | None = None, simplicity: str | None = None, emoji: bool | None = None) -> Dict[str, Any]:
    persona = _load()
    style = persona.setdefault("style", {})
    if tone is not None:
        style["tone"] = tone
    if verbosity is not None:
        style["verbosity"] = verbosity
    if simplicity is not None:
        style["simplicity"] = simplicity
    if emoji is not None:
        style["emoji"] = bool(emoji)
    save(persona)
    return persona

def add_fact(section: str, text: str) -> Dict[str, Any]:
    persona = _load()
    knowledge = persona.setdefault("knowledge", {})
    arr = knowledge.setdefault(section, [])
    if text not in arr:
        arr.append(text)
        save(persona)
    return persona
