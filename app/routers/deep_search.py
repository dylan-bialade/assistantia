from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse
from app.services.search import (
    hybrid_search, follow_and_build, rerank,
    record_feedback, load_json, save_json
)

router = APIRouter()

@router.get("/deep_search")
def deep_search(
    q: str = Query(..., min_length=2),
    max_results: int = 30,
    follow: bool = False,
    pretty: bool = False,
    personalize: bool = True
):
    try:
        raw = hybrid_search(q, max_results=max_results)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "search_engine_error", "detail": str(e)})

    results_out = follow_and_build(raw, follow=follow)
    if personalize:
        results_out = rerank(results_out, query=q)

    payload = {
        "query": q,
        "results": [it.__dict__ for it in results_out],
        "meta": {"count": len(results_out), "follow": follow, "personalize": personalize}
    }
    return JSONResponse(payload, media_type="application/json", status_code=200) if pretty else payload


@router.post("/feedback")
def feedback(url: str, liked: bool):
    record_feedback(url, liked)
    return {"ok": True, "liked": liked, "url": url}


@router.get("/ui", response_class=HTMLResponse)
def ui():
    return """
<!doctype html><html lang="fr"><head>
<meta charset="utf-8"><script src="https://cdn.tailwindcss.com"></script>
<title>Assistant IA — Recherche</title></head>
<body class="bg-gray-50 p-6">
<h1 class="text-3xl font-bold mb-4">🔎 Assistant IA — Recherche (GPU)</h1>
<div class="flex gap-2 mb-4">
  <input id="q" class="border rounded px-3 py-2 w-1/2" placeholder="Ex : tendances IA 2025">
  <label class="flex items-center gap-2"><input id="follow" type="checkbox"> Suivre liens</label>
  <button onclick="run()" class="bg-indigo-600 text-white px-4 py-2 rounded">Rechercher</button>
</div>
<div id="status" class="text-sm text-gray-600 mb-2"></div>
<div id="results" class="space-y-4"></div>
<script>
async function run(){
  const q = document.getElementById('q').value.trim();
  const follow = document.getElementById('follow').checked;
  if(!q){ return; }
  document.getElementById('status').textContent = "Recherche en cours...";
  const res = await fetch(`/deep_search?q=${encodeURIComponent(q)}&personalize=true&follow=${follow}`);
  const data = await res.json();
  const wrap = document.getElementById('results'); wrap.innerHTML="";
  for(const r of data.results){
    const d = document.createElement('div'); d.className="bg-white shadow p-4 rounded";
    d.innerHTML = `
      <a href="${r.url}" target="_blank" class="text-xl text-indigo-700 font-semibold">${r.title || r.url}</a><br>
      <small class="text-gray-500">${r.domain || ""}</small>
      <p class="mt-1 text-gray-700">${r.snippet || ""}</p>
      <div class="flex gap-3 mt-2">
        <button onclick="fb('${r.url}',true)" class="text-green-600 hover:underline">👍 intéressant</button>
        <button onclick="fb('${r.url}',false)" class="text-red-600 hover:underline">👎 sans intérêt</button>
      </div>`;
    wrap.appendChild(d);
  }
  document.getElementById('status').textContent = `${data.results.length} résultats`;
}
async function fb(url, liked){
  await fetch(`/feedback?url=${encodeURIComponent(url)}&liked=${liked}`, {method:"POST"});
}
</script>
</body></html>
    """


@router.get("/profile", response_class=HTMLResponse)
def profile():
    data = load_json("data/user_prefs.json")
    prefs = data.get("preferences", {"boost": [], "ban": []})
    hist = data.get("history", [])
    last = "".join([f"<li>{h.get('query','?')} → {h.get('domain','')} : {h.get('title','')}</li>" for h in hist[-10:]])
    return f"""
<html><body style='font-family:Arial;padding:2rem'>
<h1>🧠 Profil IA</h1>
<h2>Sites favoris (boost)</h2><ul>{''.join(f'<li>{b}</li>' for b in prefs.get('boost', []))}</ul>
<h2>Sites bannis (ban)</h2><ul>{''.join(f'<li>{b}</li>' for b in prefs.get('ban', []))}</ul>
<h2>Historique récent</h2><ul>{last or "<li>(vide)</li>"}</ul>
<form method='post' action='/reset'><button type='submit'>🔄 Réinitialiser</button></form>
</body></html>
    """


@router.post("/reset")
def reset():
    save_json("data/user_prefs.json", {"preferences": {"boost": [], "ban": []}, "history": []})
    return {"ok": True, "msg": "Réinitialisé"}
