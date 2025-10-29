# app/services/llm_local.py
"""
Client simple pour LLM local via Ollama (http://127.0.0.1:11434).
- llm_local(prompt, model="mistral", temperature=0.7)
"""

import os
import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")  # change en "llama3.1" ou autre si tu veux

def llm_local(prompt: str, model: str | None = None, temperature: float = 0.7, timeout: int = 120) -> str:
    model = model or OLLAMA_MODEL
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature}
            },
            timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")
    except Exception as e:
        return f"[Erreur LLM local] {e}"
