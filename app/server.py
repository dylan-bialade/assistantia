from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import requests, time, threading, json
from urllib.parse import urlparse
from urllib import robotparser
from fastapi.responses import HTMLResponse, Response

from duckduckgo_search import DDGS
import trafilatura
from bs4 import BeautifulSoup

print(">>> LOADED:", __file__)
USER_NAME = "Dylan"
HEADERS = {"User-Agent": "AssistantDylan/1.0 (+https://example.local) Contact:dylan@example.local"}

app = FastAPI(title="Assistant de Dylan")

# ======================== Utils communs ========================
def extract_with_bs4(html: str, max_chars: int = 1600) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:max_chars]

def fetch_page_text(url: str, timeout: int = 8, max_chars: int = 1400) -> str:
    # 1) trafilatura.fetch_url -> extract
    try:
        downloaded = trafilatura.fetch_url(url, timeout=timeout)
        if downloaded:
            txt = trafilatura.extract(downloaded) or ""
            if txt.strip():
                return txt.strip()[:max_chars]
    except Exception:
        pass
    # 2) requests + extract + fallback BS4
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.ok and resp.text:
            txt = trafilatura.extract(resp.text) or ""
            if txt.strip():
                return txt.strip()[:max_chars]
            return extract_with_bs4(resp.text, max_chars=max_chars)
    except Exception:
        pass
    return ""

# ======================== Routes de base ========================
class ChatIn(BaseModel):
    message: str

class ChatOut(BaseModel):
    reply: str

@app.get("/")
def root():
    return {"ok": True, "msg": f"Bonjour {USER_NAME}, l’API est prête."}

@app.get("/routes")
def routes():
    return [r.path for r in app.router.routes]

@app.post("/chat", response_model=ChatOut)
def chat(inp: ChatIn):
    return ChatOut(reply=f"Bonjour {USER_NAME} 👋 Tu as dit : “{inp.message}”.")

# ======================== Recherche simple ========================
@app.get("/web_fast")
def web_fast(q: str = "tendances IA en entreprise 2025", max_results: int = 3):
    out = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(q, region="fr-fr", safesearch="moderate", max_results=max_results):
                url = r.get("href") or r.get("url")
                if url:
                    out.append({"title": r.get("title") or "Résultat", "url": url})
    except Exception as e:
        return {"query": q, "error": str(e), "results": out}
    return {"query": q, "results": out}

@app.get("/web_test")
def web_test(q: str = "site:wikipedia.org intelligence artificielle", max_results: int = 2):
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(q, region="fr-fr", safesearch="moderate", max_results=max_results):
                url = r.get("href") or r.get("url")
                if not url:
                    continue
                extract = fetch_page_text(url, timeout=8, max_chars=1400)
                results.append({
                    "title": r.get("title") or "Résultat",
                    "url": url,
                    "snippet": (r.get("body") or "")[:220],
                    "extract": extract
                })
                time.sleep(0.4)
    except Exception as e:
        results.append({"title": "ERREUR", "url": "", "snippet": str(e), "extract": ""})
    return {"query": q, "results": results}

# ======================== Météo (Open-Meteo) ========================
WEATHER_DESC = {
    0:"ciel dégagé",1:"peu nuageux",2:"partiellement nuageux",3:"couvert",
    45:"brouillard",48:"brouillard givrant",51:"bruine faible",53:"bruine modérée",55:"bruine forte",
    56:"bruine verglaçante faible",57:"bruine verglaçante forte",
    61:"pluie faible",63:"pluie modérée",65:"pluie forte",66:"pluie verglaçante faible",67:"pluie verglaçante forte",
    71:"neige faible",73:"neige modérée",75:"neige forte",77:"neige en grains",
    80:"averses faibles",81:"averses modérées",82:"averses fortes",
    85:"averses de neige faibles",86:"averses de neige fortes",
    95:"orages",96:"orages avec grêle faible",99:"orages avec grêle forte",
}
def describe_weather(code: Optional[int]) -> str:
    return WEATHER_DESC.get(code, f"code météo {code}" if code is not None else "conditions inconnues")

def geocode_city(city: str) -> Dict:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city, "count": 1, "language": "fr", "format": "json"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=8); r.raise_for_status()
    data = r.json(); results = data.get("results") or []
    if not results:
        raise ValueError(f"Ville introuvable: {city}")
    top = results[0]
    return {"lat": top["latitude"], "lon": top["longitude"], "name": top.get("name"),
            "admin1": top.get("admin1"), "country": top.get("country")}

def open_meteo_tomorrow(lat: float, lon: float) -> Dict:
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat}&longitude={lon}"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
           "&timezone=Europe%2FParis")
    r = requests.get(url, headers=HEADERS, timeout=8); r.raise_for_status()
    return r.json()

@app.get("/weather")
def weather(city: str = "Castres"):
    loc = geocode_city(city)
    data = open_meteo_tomorrow(loc["lat"], loc["lon"])
    daily = data.get("daily", {})
    def pick(i, key, default=None):
        arr = daily.get(key) or []
        return arr[i] if len(arr) > i else default
    tmax = pick(1, "temperature_2m_max")
    tmin = pick(1, "temperature_2m_min")
    prcp = pick(1, "precipitation_sum")
    code = pick(1, "weathercode")
    return {
        "city": f"{loc['name']}, {loc['admin1']}, {loc['country']}",
        "coords": {"lat": loc["lat"], "lon": loc["lon"]},
        "tomorrow": {"tmin_c": tmin, "tmax_c": tmax, "precipitation_mm": prcp,
                     "weathercode": code, "description": describe_weather(code)}
    }

# ======================== Deep Search (poussé & responsable) ========================
DEFAULT_MAX_RESULTS = 50
DEFAULT_PER_DOMAIN = 5
DEFAULT_DELAY_PER_DOMAIN = 1.0
REQUEST_TIMEOUT = 8

_robots_cache: Dict[str, Optional[robotparser.RobotFileParser]] = {}
_last_access: Dict[str, float] = {}
_count_per_domain: Dict[str, int] = {}
_lock = threading.Lock()

class SearchResult(BaseModel):
    title: Optional[str]
    url: str
    snippet: Optional[str]
    extract: Optional[str] = None
    allowed_by_robots: Optional[bool] = None
    domain: Optional[str] = None

class DeepSearchOut(BaseModel):
    query: str
    results: List[SearchResult]
    meta: Dict[str, Any]

def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def can_fetch_url(url: str, user_agent: str = HEADERS["User-Agent"]) -> bool:
    domain = get_domain(url)
    if not domain:
        return False
    base = f"{urlparse(url).scheme}://{domain}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = robotparser.RobotFileParser()
        try:
            rp.set_url(base + "/robots.txt")
            rp.read()
            _robots_cache[base] = rp
        except Exception:
            _robots_cache[base] = None
            return True
    if rp is None:
        return True
    return rp.can_fetch(user_agent, url)

def polite_wait(domain: str, min_interval: float = DEFAULT_DELAY_PER_DOMAIN):
    with _lock:
        last = _last_access.get(domain)
        now = time.time()
        if last:
            wait = min_interval - (now - last)
            if wait > 0:
                time.sleep(wait)
        _last_access[domain] = time.time()

def increment_domain_count(domain: str) -> int:
    with _lock:
        c = _count_per_domain.get(domain, 0) + 1
        _count_per_domain[domain] = c
        return c

def fetch_metadata(url: str) -> Dict[str, Optional[str]]:
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    html = resp.text
    # trafilatura extract
    try:
        txt = trafilatura.extract(html) or ""
        extract = " ".join(txt.split())[:500] if txt and len(txt.strip()) > 40 else ""
    except Exception:
        extract = ""
    # title + meta description
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    snippet = meta.get("content").strip() if meta and meta.get("content") else None
    if not snippet and not extract:
        node = soup.find("p")
        if node and node.get_text(strip=True):
            snippet = node.get_text(strip=True)[:300]
    return {"title": title, "snippet": snippet, "extract": extract}

def ddg_search_raw(query: str, max_results: int = 50) -> List[Dict]:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, region="fr-fr", safesearch="moderate", max_results=max_results):
            results.append(r)
    return results

@app.get("/deep_search", response_model=DeepSearchOut)
def deep_search(
    q: str = Query(..., min_length=2),
    max_results: int = Query(DEFAULT_MAX_RESULTS, ge=1, le=200),
    follow: bool = Query(False),
    max_per_domain: int = Query(DEFAULT_PER_DOMAIN, ge=1, le=50),
    delay_per_domain: float = Query(DEFAULT_DELAY_PER_DOMAIN, ge=0.0, le=10.0),
    pretty: bool = Query(False)
):
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query trop courte")
    max_results = min(max_results, 200)

    try:
        raw = ddg_search_raw(q, max_results=max_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur moteur: {e}")

    results_out: List[SearchResult] = []
    total_followed = 0
    domain_counts_local: Dict[str, int] = {}

    for r in raw:
        url = r.get("href") or r.get("url")
        title = r.get("title") or None
        snippet_from_search = (r.get("body") or "")[:300] or None
        if not url:
            continue

        domain = get_domain(url)
        allowed = can_fetch_url(url)

        item = SearchResult(
            title=title, url=url, snippet=snippet_from_search,
            extract=None, allowed_by_robots=allowed, domain=domain
        )

        if follow and allowed:
            if domain_counts_local.get(domain, 0) < max_per_domain:
                polite_wait(domain, min_interval=delay_per_domain)
                c = increment_domain_count(domain)
                if c <= max_per_domain:
                    try:
                        meta = fetch_metadata(url)
                        item.title = item.title or meta.get("title")
                        item.snippet = item.snippet or meta.get("snippet")
                        item.extract = meta.get("extract") or None
                        total_followed += 1
                    except Exception as e:
                        item.extract = f"ERROR_FETCH:{str(e)}"
                domain_counts_local[domain] = domain_counts_local.get(domain, 0) + 1

        results_out.append(item)
        if len(results_out) >= max_results:
            break

    meta = {
        "total_results_from_search": len(raw),
        "returned_results": len(results_out),
        "follow_performed": follow,
        "total_followed": total_followed,
        "max_per_domain": max_per_domain,
        "delay_per_domain": delay_per_domain,
    }

    result = {"query": q, "results": results_out, "meta": meta}

    if pretty:
        return Response(
            content=json.dumps(result, ensure_ascii=False, indent=2),
            media_type="application/json",
        )
    return result

# ======================== UI (barre de recherche) ========================
@app.get("/ui", response_class=HTMLResponse)
def ui():
    return """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Assistant de Dylan — Deep Search</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
    .card { border-radius: 1rem; box-shadow: 0 6px 24px rgba(0,0,0,.08); }
  </style>
</head>
<body class="bg-gray-50 text-gray-900">
  <div class="max-w-5xl mx-auto p-6">
    <h1 class="text-2xl font-semibold mb-4">🔎 Assistant de Dylan — Deep Search</h1>

    <div class="card bg-white p-4 mb-6">
      <div class="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
        <div class="md:col-span-3">
          <label class="block text-sm mb-1">Requête</label>
          <input id="q" type="text" placeholder="ex: tendances IA en entreprise 2025"
                 class="w-full rounded-lg border px-3 py-2 focus:outline-none focus:ring focus:ring-indigo-200" />
        </div>
        <div>
          <label class="block text-sm mb-1">Max résultats</label>
          <input id="max_results" type="number" min="1" max="200" value="30"
                 class="w-full rounded-lg border px-3 py-2 focus:outline-none focus:ring focus:ring-indigo-200" />
        </div>
        <div>
          <label class="block text-sm mb-1">Max/domain</label>
          <input id="max_per_domain" type="number" min="1" max="50" value="3"
                 class="w-full rounded-lg border px-3 py-2 focus:outline-none focus:ring focus:ring-indigo-200" />
        </div>
        <div>
          <label class="block text-sm mb-1">Delay/domain (s)</label>
          <input id="delay_per_domain" type="number" step="0.1" min="0" max="10" value="1.2"
                 class="w-full rounded-lg border px-3 py-2 focus:outline-none focus:ring focus:ring-indigo-200" />
        </div>
        <div class="flex items-center gap-3">
          <label class="inline-flex items-center gap-2">
            <input id="follow" type="checkbox" class="h-4 w-4" />
            <span>Suivre liens</span>
          </label>
          <label class="inline-flex items-center gap-2">
            <input id="pretty" type="checkbox" class="h-4 w-4" />
            <span>JSON joli</span>
          </label>
        </div>
        <div class="md:col-span-6 flex gap-3">
          <button id="go" class="rounded-lg bg-indigo-600 text-white px-4 py-2 hover:bg-indigo-700">
            Rechercher
          </button>
          <button id="clear" class="rounded-lg bg-gray-200 text-gray-800 px-4 py-2 hover:bg-gray-300">
            Effacer
          </button>
        </div>
      </div>
    </div>

    <div id="status" class="text-sm text-gray-600 mb-3"></div>
    <div id="results" class="space-y-4"></div>

    <details class="mt-8">
      <summary class="cursor-pointer text-sm text-gray-600">Voir la réponse JSON brute</summary>
      <pre id="raw" class="mono text-xs bg-white p-4 rounded-lg overflow-auto mt-2"></pre>
    </details>
  </div>

<script>
const $ = (sel) => document.querySelector(sel);
const esc = (s) => (s || "").toString().replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]) );

async function run() {
  const q = $("#q").value.trim();
  if (!q) { $("#status").textContent = "Saisis une requête."; return; }

  const max_results = +$("#max_results").value || 30;
  const follow = $("#follow").checked;
  const max_per_domain = +$("#max_per_domain").value || 3;
  const delay_per_domain = +$("#delay_per_domain").value || 1.2;
  const pretty = $("#pretty").checked;

  const params = new URLSearchParams({
    q, max_results, follow, max_per_domain, delay_per_domain, pretty
  });

  const url = `/deep_search?${params.toString()}`;
  $("#status").textContent = "Recherche en cours…";
  $("#results").innerHTML = "";
  $("#raw").textContent = "";

  try {
    const res = await fetch(url);
    const txt = await res.text();

    let data;
    try { data = JSON.parse(txt); } catch { data = null; }

    if (data && data.results) {
      renderCards(data);
      $("#raw").textContent = JSON.stringify(data, null, 2);
      $("#status").textContent = `OK — ${data.results.length} résultats (follow=${data.meta.follow_performed ? "oui" : "non"})`;
    } else {
      $("#raw").textContent = txt;
      $("#status").textContent = "Réponse formatée (pretty)";
    }
  } catch (e) {
    $("#status").textContent = "Erreur: " + e.message;
  }
}

function renderCards(data) {
  const wrap = $("#results");
  wrap.innerHTML = "";
  for (const it of data.results) {
    const allowed = it.allowed_by_robots === false
      ? '<span class="text-xs bg-red-100 text-red-700 px-2 py-1 rounded-full">robots.txt: non</span>'
      : '<span class="text-xs bg-green-100 text-green-700 px-2 py-1 rounded-full">robots.txt: ok</span>';

    const card = document.createElement("div");
    card.className = "card bg-white p-4";
    card.innerHTML = `
      <div class="flex flex-wrap items-center gap-2 mb-2">
        <a class="text-lg font-medium text-indigo-700 hover:underline" href="${esc(it.url)}" target="_blank" rel="noopener">
          ${esc(it.title || it.url)}
        </a>
        <span class="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded-full">${esc(it.domain || "")}</span>
        ${allowed}
      </div>
      ${it.snippet ? `<p class="text-sm text-gray-700 mb-2">${esc(it.snippet)}</p>` : ``}
      ${it.extract ? `<details class="mt-1">
          <summary class="text-sm text-gray-600 cursor-pointer">Extrait</summary>
          <p class="text-sm text-gray-800 mt-1">${esc(it.extract)}</p>
      </details>` : ``}
      <div class="mt-2 text-xs text-gray-500 mono">${esc(it.url)}</div>
    `;
    wrap.appendChild(card);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#go").addEventListener("click", run);
  $("#clear").addEventListener("click", () => {
    $("#q").value = "";
    $("#results").innerHTML = "";
    $("#raw").textContent = "";
    $("#status").textContent = "";
  });
  $("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
});
</script>
</body>
</html>
    """
