# app/routers/persona.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, HTMLResponse

router = APIRouter(tags=["persona"])

# ====== Try to use the central manager; fallback to local JSON if not available ======
try:
    from app.neurone.persona_manager import (  # type: ignore
        load_persona as _pm_load,
        save_persona as _pm_save,
        update_persona as _pm_update,
        reset_persona as _pm_reset,
        PERSONA_PATH as _PM_PATH,
    )
    _USE_PM = True
except Exception:
    _USE_PM = False
    # Fallback simple: data/persona.json
    ROOT_DIR = Path(__file__).resolve().parents[2]  # .../project
    DATA_DIR = ROOT_DIR / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _PM_PATH = DATA_DIR / "persona.json"

    _DEFAULT_PERSONA: Dict[str, Any] = {
        "name": "Andy",
        "creator": "Dylan",
        "mission": "Aider Dylan (dev/ops/études) avec clarté, honnêteté et efficacité.",
        "style": {
            "tone": "friendly",
            "verbosity": "normal",    # "brief" | "normal" | "detailed"
            "simplicity": "simple",   # "simple" | "technical"
            "emoji": True
        },
        "knowledge": {
            "domains": ["dev", "ops", "linux", "bts sio", "symfony", "react", "android"],
            "preferences": {
                "fr_language": True,
                "explain_why": True
            }
        },
        "rules": [
            "Toujours être utile et concret.",
            "Poser des questions si le besoin n’est pas clair.",
            "Préférer des explications simples quand c’est possible."
        ]
    }

    def _pm_load() -> Dict[str, Any]:
        if _PM_PATH.exists():
            try:
                return json.loads(_PM_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        _PM_PATH.write_text(json.dumps(_DEFAULT_PERSONA, ensure_ascii=False, indent=2), encoding="utf-8")
        return _DEFAULT_PERSONA

    def _pm_save(data: Dict[str, Any]) -> None:
        _PM_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _deep_update(dst: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                dst[k] = _deep_update(dst[k], v)
            else:
                dst[k] = v
        return dst

    def _pm_update(patch: Dict[str, Any]) -> Dict[str, Any]:
        data = _pm_load()
        data = _deep_update(data, patch or {})
        _pm_save(data)
        return data

    def _pm_reset() -> Dict[str, Any]:
        _pm_save(_DEFAULT_PERSONA)
        return _DEFAULT_PERSONA

# ====== Routes ======

@router.get("/persona")
def get_persona():
    """Retourne l’état courant du persona (JSON)."""
    data = _pm_load()
    return {"ok": True, "persona": data, "source": "manager" if _USE_PM else "fallback"}

@router.patch("/persona")
def patch_persona(patch: Dict[str, Any] = Body(..., description="Patch JSON (partial update)")):
    """
    Mise à jour partielle du persona. Exemples de payload :
    { "name": "Andy v2" }
    { "style": { "verbosity": "detailed", "emoji": false } }
    { "mission": "Expliquer simplement et coder proprement." }
    """
    try:
        updated = _pm_update(patch or {})
        return {"ok": True, "persona": updated, "path": str(_PM_PATH)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "detail": str(e)})

@router.post("/persona/reset")
def reset_persona():
    """Réinitialise le persona aux valeurs par défaut."""
    try:
        base = _pm_reset()
        return {"ok": True, "persona": base, "path": str(_PM_PATH)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "detail": str(e)})

@router.get("/persona_ui", response_class=HTMLResponse)
def persona_ui():
    """Petite UI pour consulter / modifier le persona sans outil externe."""
    html = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<title>Persona Manager</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 2rem; max-width: 940px; }}
  h1 {{ margin-bottom: .25rem; }}
  .muted {{ color: #666; }}
  textarea {{ width: 100%; height: 320px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
  .row {{ display:flex; gap: .5rem; margin-top: .75rem; }}
  button {{ padding: .6rem 1rem; border: 0; border-radius: .5rem; background:#4f46e5; color:#fff; cursor:pointer; }}
  button:hover {{ background:#4338ca; }}
  .ghost {{ background:#e5e7eb; color:#111; }}
  pre {{ background:#f7f7f7; padding: .75rem; border-radius: .5rem; overflow:auto; }}
</style>
</head>
<body>
  <h1>🧩 Persona</h1>
  <p class="muted">Chemin: <code>{str(_PM_PATH)}</code> — source: <b>{"manager" if _USE_PM else "fallback"}</b></p>

  <div class="row">
    <button onclick="loadPersona()">Recharger</button>
    <button class="ghost" onclick="resetPersona()">Réinitialiser</button>
    <button onclick="savePersona()">Enregistrer</button>
  </div>

  <h3>JSON</h3>
  <textarea id="json"></textarea>
  <pre id="status"></pre>

<script>
async function loadPersona(){{
  const st = document.getElementById('status');
  st.textContent = "Chargement…";
  const res = await fetch('/persona');
  const data = await res.json();
  document.getElementById('json').value = JSON.stringify(data.persona, null, 2);
  st.textContent = "OK";
}}

async function savePersona(){{
  const st = document.getElementById('status');
  st.textContent = "Sauvegarde…";
  try {{
    const obj = JSON.parse(document.getElementById('json').value || "{{}}");
    const res = await fetch('/persona', {{
      method: 'PATCH',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify(obj)
    }});
    const data = await res.json();
    st.textContent = data.ok ? ("✅ Sauvegardé: " + (data.path||"")) : ("❌ " + data.detail);
  }} catch(e) {{
    st.textContent = "❌ JSON invalide: " + e;
  }}
}}

async function resetPersona(){{
  const st = document.getElementById('status');
  if (!confirm("Réinitialiser le persona ?")) return;
  st.textContent = "Reset…";
  const res = await fetch('/persona/reset', {{ method:'POST' }});
  const data = await res.json();
  document.getElementById('json').value = JSON.stringify(data.persona, null, 2);
  st.textContent = data.ok ? ("✅ Réinitialisé") : ("❌ " + data.detail);
}}

loadPersona();
</script>
</body>
</html>"""
    return HTMLResponse(html)
