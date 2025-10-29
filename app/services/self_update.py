# app/services/self_update.py
"""
Génération d’améliorations de code par LLM local + journalisation de notes.
- propose_code_improvement(objective) -> str
- add_note(note) / list_notes()       -> gestion des notes affichées dans /self_review
"""

from pathlib import Path
from datetime import datetime
from typing import List

from app.services.llm_local import llm_local
from app.services.memory import save_proposal  # ⬅️ stocke les patchs générés

NOTES_PATH = Path("data/self_notes.txt")
NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)

def add_note(note: str) -> None:
    """
    Ajoute une note de self-review (affichée dans /self_review).
    """
    ts = datetime.utcnow().isoformat() + "Z"
    with NOTES_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {note}\n")

def list_notes() -> List[str]:
    """
    Liste les notes existantes (format texte).
    """
    if not NOTES_PATH.exists():
        return []
    with NOTES_PATH.open("r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]

def propose_code_improvement(objective: str) -> str:
    """
    Demande au LLM local de proposer un patch Python (dans un bloc ```python ... ```),
    enregistre la proposition et retourne le texte brut.
    """
    prompt = (
        "Tu es Andy, un assistant qui propose des améliorations de code utiles.\n"
        "Objectif d'amélioration:\n"
        f"{objective}\n\n"
        "Propose un patch **complet** en Python, clairement délimité dans un bloc Markdown:\n"
        "```python\n# ton code ici\n```\n"
        "Le patch doit être exécutable et cohérent.\n"
    )
    result = llm_local(prompt)
    if not isinstance(result, str) or not result.strip():
        result = "[Erreur] LLM local n’a rien retourné."

    # Journalise le patch dans la mémoire
    save_proposal(objective, result, meta={"source": "self_propose"})

    # Ajoute une note visible dans /self_review
    add_note(f"Proposition générée pour: {objective}")

    return result
