# =============================
# AssistantIA - Setup Structure
# =============================

$base = "C:\Users\dylan\assistantia"
$app  = "$base\app"

$dirs = @(
  $base,
  $app,
  "$app\routers",
  "$app\services",
  "$app\static"
)

Write-Host "📁 Création des dossiers..."
foreach ($d in $dirs) {
  if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

# --- fichiers __init__.py ---
@'
'@ | Out-File "$app\__init__.py" -Encoding utf8
@'
'@ | Out-File "$app\routers\__init__.py" -Encoding utf8
@'
'@ | Out-File "$app\services\__init__.py" -Encoding utf8

# --- app\main.py ---
@'
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from pathlib import Path

from .routers.deep_search import router as deep_search_router
from .routers.weather import router as weather_router
from .routers.feedback import router as feedback_router
from .database import init_db

print(">>> LOADED:", __file__)
USER_NAME = "Dylan"

app = FastAPI(title="Assistant de Dylan (modulaire)")

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/")
def root():
    return {"ok": True, "msg": f"Bonjour {USER_NAME}, l’API est prête."}

@app.get("/routes")
def routes():
    return [r.path for r in app.router.routes]

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.get("/ui", response_class=HTMLResponse)
def ui():
    html = (BASE_DIR / "static" / "ui.html").read_text(encoding="utf-8")
    return HTMLResponse(html)

# Inclure les routers
app.include_router(deep_search_router, prefix="")
app.include_router(weather_router, prefix="")
app.include_router(feedback_router, prefix="")
'@ | Out-File "$app\main.py" -Encoding utf8

# --- app\models.py ---
@'
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class ChatIn(BaseModel):
    message: str

class ChatOut(BaseModel):
    reply: str

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

class FeedbackIn(BaseModel):
    url: str
    domain: Optional[str] = None
    title: Optional[str] = None
    label: str  # 'like' | 'dislike'

class PrefsIn(BaseModel):
    preferred_domains: Optional[str] = ""
    blocked_domains: Optional[str] = ""
    preferred_keywords: Optional[str] = ""
    blocked_keywords: Optional[str] = ""
    like_weight: Optional[float] = 1.0
    dislike_weight: Optional[float] = -1.0
    domain_boost: Optional[float] = 0.6
    keyword_boost: Optional[float] = 0.4
'@ | Out-File "$app\models.py" -Encoding utf8

# --- app\database.py ---
@'
import sqlite3
from pathlib import Path

USER_NAME = "Dylan"
DB_PATH = Path(__file__).resolve().parent / "prefs.db"

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db(); cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        user TEXT NOT NULL,
        url TEXT NOT NULL,
        domain TEXT,
        title TEXT,
        label TEXT CHECK(label IN ('like','dislike')) NOT NULL
    );""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS prefs (
        id INTEGER PRIMARY KEY CHECK (id=1),
        user TEXT NOT NULL,
        preferred_domains TEXT DEFAULT '',
        blocked_domains TEXT DEFAULT '',
        preferred_keywords TEXT DEFAULT '',
        blocked_keywords TEXT DEFAULT '',
        like_weight REAL DEFAULT 1.0,
        dislike_weight REAL DEFAULT -1.0,
        domain_boost REAL DEFAULT 0.6,
        keyword_boost REAL DEFAULT 0.4
    );""")
    cur.execute("INSERT OR IGNORE INTO prefs (id, user) VALUES (1, ?)", (USER_NAME,))
    conn.commit(); conn.close()
'@ | Out-File "$app\database.py" -Encoding utf8

# --- app\services\extract.py ---
@'
import requests, time, threading
from urllib.parse import urlparse
from urllib import robotparser
from bs4 import BeautifulSoup
import trafilatura

HEADERS = {"User-Agent": "AssistantDylan/1.0 (+https://example.local) Contact:dylan@example.local"}
REQUEST_TIMEOUT = 8
DEFAULT_DELAY_PER_DOMAIN = 1.0

_robots_cache = {}
_last_access = {}
_lock = threading.Lock()

def extract_with_bs4(html: str, max_chars: int = 1600) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script","style","noscript"]): tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:max_chars]

def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def can_fetch_url(url: str, user_agent: str = HEADERS["User-Agent"]) -> bool:
    dom = get_domain(url)
    if not dom: return False
    base = f"{urlparse(url).scheme}://{dom}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = robotparser.RobotFileParser()
        try:
            rp.set_url(base + "/robots.txt"); rp.read()
            _robots_cache[base] = rp
        except Exception:
            _robots_cache[base] = None
            return True
    if rp is None: return True
    return rp.can_fetch(user_agent, url)

def polite_wait(domain: str, min_interval: float = DEFAULT_DELAY_PER_DOMAIN):
    with _lock:
        last = _last_access.get(domain)
        now = time.time()
        if last:
            wait = min_interval - (now - last)
            if wait > 0: time.sleep(wait)
        _last_access[domain] = time.time()

def fetch_metadata(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    html = resp.text
    try:
        txt = trafilatura.extract(html) or ""
        extract = " ".join(txt.split())[:500] if txt and len(txt.strip()) > 40 else ""
    except Exception:
        extract = ""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    meta = soup.find("meta", attrs={"name":"description"}) or soup.find("meta", attrs={"property":"og:description"})
    snippet = meta.get("content").strip() if meta and meta.get("content") else None
    if not snippet and not extract:
        node = soup.find("p")
        if node and node.get_text(strip=True):
            snippet = node.get_text(strip=True)[:300]
    return {"title": title, "snippet": snippet, "extract": extract}
'@ | Out-File "$app\services\extract.py" -Encoding utf8

# --- app\services\prefs.py ---
@'
from ..database import db
from ..models import SearchResult

def load_prefs():
    conn = db()
    row = conn.execute("SELECT * FROM prefs WHERE id=1").fetchone()
    conn.close()
    if not row:
        return {}
    def split_csv(s):
        return [x.strip().lower() for x in (s or "").split(",") if x.strip()]
    return {
        "preferred_domains": set(split_csv(row["preferred_domains"])),
        "blocked_domains": set(split_csv(row["blocked_domains"])),
        "preferred_keywords": set(split_csv(row["preferred_keywords"])),
        "blocked_keywords": set(split_csv(row["blocked_keywords"])),
        "like_weight": float(row["like_weight"]),
        "dislike_weight": float(row["dislike_weight"]),
        "domain_boost": float(row["domain_boost"]),
        "keyword_boost": float(row["keyword_boost"]),
    }

def get_feedback_counts():
    conn = db(); cur = conn.cursor()
    likes_domain = {r["domain"]: r["c"] for r in cur.execute("SELECT domain, COUNT(*) c FROM feedback WHERE label='like' GROUP BY domain")}
    dislikes_domain = {r["domain"]: r["c"] for r in cur.execute("SELECT domain, COUNT(*) c FROM feedback WHERE label='dislike' GROUP BY domain")}
    likes_url = {r["url"]: r["c"] for r in cur.execute("SELECT url, COUNT(*) c FROM feedback WHERE label='like' GROUP BY url")}
    dislikes_url = {r["url"]: r["c"] for r in cur.execute("SELECT url, COUNT(*) c FROM feedback WHERE label='dislike' GROUP BY url")}
    conn.close()
    return likes_domain, dislikes_domain, likes_url, dislikes_url

def score_result(item: SearchResult, query: str, prefs: dict, fb_counts, base_rank: int) -> float:
    domain = (item.domain or "").lower()
    title = (item.title or "")
    snippet = (item.snippet or "")
    text = f"{title} {snippet}".lower()
    base = 1.0 / (base_rank + 1)
    likes_domain, dislikes_domain, likes_url, dislikes_url = fb_counts
    s_fb = 0.0
    s_fb += likes_domain.get(domain, 0) * prefs["like_weight"]
    s_fb += dislikes_domain.get(domain, 0) * prefs["dislike_weight"]
    s_fb += likes_url.get(item.url, 0) * (prefs["like_weight"] * 1.5)
    s_fb += dislikes_url.get(item.url, 0) * (prefs["dislike_weight"] * 1.5)
    s_dom = 0.0
    if domain in prefs["preferred_domains"]: s_dom += prefs["domain_boost"]
    if domain in prefs["blocked_domains"]:   s_dom -= prefs["domain_boost"]
    s_kw = 0.0
    if any(k in text for k in prefs["preferred_keywords"]): s_kw += prefs["keyword_boost"]
    if any(k in text for k in prefs["blocked_keywords"]):   s_kw -= prefs["keyword_boost"]
    return base + s_fb + s_dom + s_kw
'@ | Out-File "$app\services\prefs.py" -Encoding utf8

# --- app\services\search.py ---
@'
from typing import List, Dict
from duckduckgo_search import DDGS
from .extract import can_fetch_url, polite_wait, fetch_metadata, get_domain
from ..models import SearchResult
from .prefs import load_prefs, get_feedback_counts, score_result

def ddg_search_raw(query: str, max_results: int = 50) -> List[Dict]:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, region="fr-fr", safesearch="moderate", max_results=max_results):
            results.append(r)
    return results

def follow_and_build(results_raw: List[Dict], follow: bool, max_per_domain: int, delay_per_domain: float) -> List[SearchResult]:
    results_out: List[SearchResult] = []
    domain_counts_local: Dict[str, int] = {}
    for r in results_raw:
        url = r.get("href") or r.get("url")
        title = r.get("title") or None
        snippet_from_search = (r.get("body") or "")[:300] or None
        if not url: 
            continue
        domain = get_domain(url)
        allowed = can_fetch_url(url)
        item = SearchResult(title=title, url=url, snippet=snippet_from_search,
                            extract=None, allowed_by_robots=allowed, domain=domain)
        if follow and allowed:
            if domain_counts_local.get(domain, 0) < max_per_domain:
                polite_wait(domain, min_interval=delay_per_domain)
                try:
                    meta = fetch_metadata(url)
                    item.title = item.title or meta.get("title")
                    item.snippet = item.snippet or meta.get("snippet")
                    item.extract = meta.get("extract") or None
                except Exception as e:
                    item.extract = f"ERROR_FETCH:{str(e)}"
                domain_counts_local[domain] = domain_counts_local.get(domain, 0) + 1
        results_out.append(item)
    return results_out

def rerank(results_out: List[SearchResult], query: str) -> List[SearchResult]:
    prefs = load_prefs()
    fb_counts = get_feedback_counts()
    scored = []
    for idx, it in enumerate(results_out):
        s = score_result(it, query, prefs, fb_counts, base_rank=idx)
        scored.append((s, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored]
'@ | Out-File "$app\services\search.py" -Encoding utf8

# --- app\routers\deep_search.py ---
@'
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response
import json

from ..models import DeepSearchOut
from ..services.search import ddg_search_raw, follow_and_build, rerank

router = APIRouter()
DEFAULT_MAX_RESULTS = 50

@router.get("/deep_search", response_model=DeepSearchOut)
def deep_search(
    q: str = Query(..., min_length=2),
    max_results: int = Query(DEFAULT_MAX_RESULTS, ge=1, le=200),
    follow: bool = Query(False),
    max_per_domain: int = Query(5, ge=1, le=50),
    delay_per_domain: float = Query(1.0, ge=0.0, le=10.0),
    pretty: bool = Query(False),
    personalize: bool = Query(True)
):
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query trop courte")
    max_results = min(max_results, 200)

    try:
        raw = ddg_search_raw(q, max_results=max_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur moteur: {e}")

    results_out = follow_and_build(raw, follow=follow, max_per_domain=max_per_domain, delay_per_domain=delay_per_domain)
    results_out = results_out[:max_results]

    if personalize:
        results_out = rerank(results_out, query=q)

    meta = {
        "total_results_from_search": len(raw),
        "returned_results": len(results_out),
        "follow_performed": follow,
        "max_per_domain": max_per_domain,
        "delay_per_domain": delay_per_domain,
        "personalized": personalize
    }
    result = {"query": q, "results": results_out, "meta": meta}

    if pretty:
        return Response(content=json.dumps(result, ensure_ascii=False, indent=2), media_type="application/json")
    return result
'@ | Out-File "$app\routers\deep_search.py" -Encoding utf8

# --- app\routers\weather.py ---
@'
from fastapi import APIRouter
import requests
from typing import Dict, Optional

router = APIRouter()
HEADERS = {"User-Agent": "AssistantDylan/1.0 (+https://example.local)"}

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
    if not results: raise ValueError(f"Ville introuvable: {city}")
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

@router.get("/weather")
def weather(city: str = "Castres"):
    loc = geocode_city(city)
    data = open_meteo_tomorrow(loc["lat"], loc["lon"])
    daily = data.get("daily", {})
    def pick(i, key, default=None):
        arr = daily.get(key) or []
        return arr[i] if len(arr) > i else default
    tmax = pick(1,"temperature_2m_max"); tmin = pick(1,"temperature_2m_min")
    prcp = pick(1,"precipitation_sum"); code = pick(1,"weathercode")
    return {
        "city": f"{loc['name']}, {loc['admin1']}, {loc['country']}",
        "coords": {"lat": loc["lat"], "lon": loc["lon"]},
        "tomorrow": {"tmin_c": tmin, "tmax_c": tmax, "precipitation_mm": prcp,
                     "weathercode": code, "description": describe_weather(code)}
    }
'@ | Out-File "$app\routers\weather.py" -Encoding utf8

# --- app\routers\feedback.py ---
@'
from fastapi import APIRouter, HTTPException
from datetime import datetime
from ..models import FeedbackIn, PrefsIn
from ..database import db
from ..services.prefs import load_prefs

router = APIRouter()
USER_NAME = "Dylan"

@router.post("/feedback")
def post_feedback(fb: FeedbackIn):
    label = fb.label.lower()
    if label not in ("like","dislike"):
        raise HTTPException(400, "label doit être 'like' ou 'dislike'")
    conn = db()
    conn.execute(
        "INSERT INTO feedback (created_at, user, url, domain, title, label) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), USER_NAME, fb.url, (fb.domain or ""), (fb.title or ""), label)
    )
    conn.commit(); conn.close()
    return {"ok": True}

@router.get("/prefs")
def get_prefs():
    return load_prefs()

@router.post("/prefs")
def set_prefs(p: PrefsIn):
    conn = db()
    conn.execute("""
      UPDATE prefs SET
        preferred_domains=?, blocked_domains=?, preferred_keywords=?, blocked_keywords=?,
        like_weight=?, dislike_weight=?, domain_boost=?, keyword_boost=?
      WHERE id=1
    """, (
        p.preferred_domains or "",
        p.blocked_domains or "",
        p.preferred_keywords or "",
        p.blocked_keywords or "",
        float(p.like_weight or 1.0),
        float(p.dislike_weight or -1.0),
        float(p.domain_boost or 0.6),
        float(p.keyword_boost or 0.4),
    ))
    conn.commit(); conn.close()
    return {"ok": True, "prefs": load_prefs()}
'@ | Out-File "$app\routers\feedback.py" -Encoding utf8

# --- app\static\ui.html ---
@'
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
          <button id="go" class="rounded-lg bg-indigo-600 text-white px-4 py-2 hover:bg-indigo-700">Rechercher</button>
          <button id="clear" class="rounded-lg bg-gray-200 text-gray-800 px-4 py-2 hover:bg-gray-300">Effacer</button>
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

  const params = new URLSearchParams({ q, max_results, follow, max_per_domain, delay_per_domain, pretty, personalize: true });
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

async function sendFeedback(item, label) {
  try {
    await fetch("/feedback", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ url: item.url, domain: item.domain, title: item.title, label })
    });
  } catch (e) { console.warn("feedback error", e); }
}

function renderCards(data) {
  const wrap = $("#results"); wrap.innerHTML = "";
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
      ${it.extract ? `<details class="mt-1"><summary class="text-sm text-gray-600 cursor-pointer">Extrait</summary><p class="text-sm text-gray-800 mt-1">${esc(it.extract)}</p></details>` : ``}
      <div class="mt-2 flex gap-2">
        <button class="px-3 py-1 rounded bg-green-100 text-green-800 hover:bg-green-200 text-sm" data-act="like">👍 Utile</button>
        <button class="px-3 py-1 rounded bg-red-100 text-red-800 hover:bg-red-200 text-sm" data-act="dislike">👎 Sans intérêt</button>
      </div>
      <div class="mt-2 text-xs text-gray-500 mono">${esc(it.url)}</div>
    `;
    card.querySelector('[data-act="like"]').addEventListener("click", async () => { await sendFeedback(it, "like"); card.style.outline = "2px solid #16a34a55"; });
    card.querySelector('[data-act="dislike"]').addEventListener("click", async () => { await sendFeedback(it, "dislike"); card.style.outline = "2px solid #dc262655"; });
    wrap.appendChild(card);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#go").addEventListener("click", run);
  $("#clear").addEventListener("click", () => { $("#q").value = ""; $("#results").innerHTML = ""; $("#raw").textContent = ""; $("#status").textContent = ""; });
  $("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
});
</script>
</body>
</html>
'@ | Out-File "$app\static\ui.html" -Encoding utf8

# --- run.bat (ASCII pour éviter le BOM) ---
@'
@echo off
setlocal
cd /d %~dp0
call .\.venv\Scripts\activate
cd app
python -m uvicorn app.main:app --reload --port 8002 --reload-exclude "..\.venv"
endlocal
'@ | Out-File "$base\run.bat" -Encoding ascii

Write-Host "`n✅ Structure complète créée dans $base"
Write-Host "➡️ Ensuite :"
Write-Host "   1) cd $base"
Write-Host "   2) py -3.11 -m venv .venv"
Write-Host "   3) .\.venv\Scripts\Activate"
Write-Host "   4) pip install fastapi uvicorn duckduckgo-search trafilatura beautifulsoup4 requests starlette"
Write-Host "   5) .\run.bat"
