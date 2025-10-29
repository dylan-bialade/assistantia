# app/routers/self_update_router.py
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.services.self_update import propose_code_improvement, add_note, list_notes
from app.services.verification import verify_patch
from app.services.trace_logger import write_code_trace  # utilisé par /log_code si tu l'as

router = APIRouter(tags=["self-update"])

# =========================================================
# ⚠️ IMPORTANT :
# Si tu gardes cette route /self_review ici,
# supprime/renomme la route /self_review dans app/main.py
# pour éviter le conflit.
# =========================================================

@router.get("/self_review", response_class=HTMLResponse)
def self_review_ui() -> str:
    try:
        notes = list_notes()
    except Exception:
        notes = []

    items = "".join(f"<li>{n}</li>" for n in notes) or "<li>(aucune note)</li>"

    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Self Review</title>
  <style>
    body { font-family: Arial, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 2rem; max-width: 1100px; margin: 0 auto; background:#0d1117; color:#f5f5f5; }
    textarea { width: 100%; max-width: 1100px; background:#151a24; color:#f5f5f5; border:1px solid #333; border-radius:8px; }
    pre { white-space: pre-wrap; background: #151a24; padding: 1rem; border-radius: 8px; max-width: 1100px; overflow:auto; color:#00e676; }
    button { padding: .6rem 1rem; border-radius: .5rem; background: #ff8800; color: #000; border: 0; cursor: pointer; font-weight:600; }
    button:hover { background: #ffaa33; }
    .muted { color: #aaa; font-size: .95rem; }
    .status { margin-top: .5rem; font-size: .9rem; color: #ccc; }
    .ok { color: #00bd74; }
    .err { color: #ff6b6b; }
    .card { background: #0f1420; border-radius: 10px; padding: 1rem; box-shadow: 0 6px 24px rgba(0,0,0,.25); margin-top: 1rem; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    ul { padding-left: 1.2rem; }
    a { color:#7aa2ff; }
  </style>
</head>
<body>
  <h1>🛠️ Auto-amélioration (avec vérification)</h1>

  <form onsubmit="event.preventDefault(); gen();">
    <p class="muted">Objectif (ex: “accélérer la recherche”, “mieux classer les résultats”, etc.)</p>
    <textarea id="objective" rows="4" placeholder="Décris l'objectif d'amélioration..."></textarea><br /><br />
    <button type="submit">🚀 Générer + Vérifier</button>
    <button type="button" onclick="applyPatch()">💾 Valider et appliquer</button>
    <div id="status" class="status"></div>
  </form>

  <div class="grid">
    <div class="card">
      <h2>Proposition d'Andy</h2>
      <pre id="out"></pre>
    </div>
    <div class="card">
      <h2>Verdict</h2>
      <pre id="verdict"></pre>
    </div>
  </div>

  <h2>📝 Notes</h2>
  <ul>__NOTES__</ul>

  <script>
    async function gen(){
      const obj = document.getElementById('objective').value || "";
      const statusEl = document.getElementById('status');
      const outEl = document.getElementById('out');
      const verEl = document.getElementById('verdict');

      outEl.textContent = "";
      verEl.textContent = "";
      statusEl.textContent = "⏳ Génération en cours...";

      try {
        // 1) Génération du patch
        const res = await fetch(`/self_propose?objective=${encodeURIComponent(obj)}`);
        const data = await res.json();
        const patch = (data && typeof data.patch === "string") ? data.patch : "";
        outEl.textContent = patch || data.detail || JSON.stringify(data, null, 2);

        // 2) Vérification côté serveur (retourne syntax + verdict)
        const vres = await fetch("/self_verify", {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ objective: obj, patch })
        });
        const vjson = await vres.json();
        verEl.textContent = JSON.stringify(vjson, null, 2);

        // 3) Journalisation (trace)
        try {
          const lres = await fetch("/log_code", {
            method: "POST",
            headers: {"Content-Type":"application/json"},
            body: JSON.stringify({ code: patch || "(empty-patch)", source: "self_review", meta: { objective: obj } })
          });
          const ljson = await lres.json();
          if (lres.ok && ljson && ljson.ok) {
            statusEl.innerHTML = `<span class="ok">✅ Trace écrite : ${ljson.path}</span>`;
          } else {
            statusEl.innerHTML = `<span class="err">❌ Journalisation échouée</span>`;
          }
        } catch (e) {
          console.warn("log_code failed:", e);
        }
      } catch (e) {
        outEl.textContent = "Erreur: " + e;
        statusEl.innerHTML = `<span class="err">❌ Exception: ${e}</span>`;
        console.error(e);
      }
    }

    async function applyPatch(){
      const full = document.getElementById("out").textContent;

      // Tente d'extraire un bloc ```lang\n...\n```
      const m = full.match(/```(\w+)?\\s*\\n([\\s\\S]*?)```/m);
      const code = m ? m[2] : full;

      const file = prompt("Nom du fichier à modifier (ex: app/services/search.py)");
      if (!file) return alert("Fichier non spécifié");

      try {
        const resp = await fetch("/apply_patch", {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ file_path: file, new_code: code })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Erreur HTTP");
        alert("✅ " + data.detail);
        document.getElementById('status').textContent = "💾 Code appliqué avec succès.";
      } catch (e) {
        alert("❌ Erreur d’application : " + e.message);
        document.getElementById('status').textContent = "⚠️ Erreur d'application du patch.";
      }
    }
  </script>
</body>
</html>
    """.replace("__NOTES__", items)

    return html


@router.get("/self_propose")
def self_propose(objective: str = Query(..., min_length=5)):
    """
    Génère une proposition de patch (code brut) via le LLM local.
    """
    try:
        patch = propose_code_improvement(objective)
        add_note(f"Proposition générée pour: {objective}")
        return {"ok": True, "patch": patch}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "detail": str(e)})


# ---- vérification serveur du patch généré ----

class SelfVerifyIn(BaseModel):
    objective: str = Field(..., min_length=3)
    patch: str = Field(..., description="Code/patch proposé (tel qu'affiché).")
    context: Optional[str] = Field(default=None, description="Optionnel: extrait du code existant pour aider la vérification.")

@router.post("/self_verify")
def self_verify(inp: SelfVerifyIn):
    """
    Vérifie automatiquement le patch d'Andy:
      - check syntaxe locale (si bloc ```lang ...)
      - verdict structuré par le LLM
    """
    try:
        result = verify_patch(inp.objective, inp.patch, context=inp.context)
        return {"ok": True, **result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "detail": str(e)})
