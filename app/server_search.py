"""
server_search.py
Endpoint responsable pour recherche "poussée" :
- /deep_search?q=...&max_results=50&follow=true
- Respecte robots.txt, rate-limit par domaine, plafond par domaine, délai global.
"""

from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from duckduckgo_search import DDGS
from urllib.parse import urlparse
from urllib import robotparser
import requests
import time
import trafilatura
from bs4 import BeautifulSoup
import threading

# ---------- Configurable ----------
USER_AGENT = "AssistantDylan/1.0 (+https://example.local contact:dylan@example.local)"
DEFAULT_MAX_RESULTS = 50           # plafond global (ne pas trop pousser)
DEFAULT_PER_DOMAIN = 5             # max pages suivies par domaine
DEFAULT_DELAY_PER_DOMAIN = 1.0     # secondes entre requêtes sur le même domaine
REQUEST_TIMEOUT = 8                # timeout HTTP
# ----------------------------------

app = FastAPI(title="Assistant Search (poussé et responsable)")

# In-memory caches / counters (process-local)
_robots_cache: Dict[str, Optional[robotparser.RobotFileParser]] = {}
_last_access: Dict[str, float] = {}
_count_per_domain: Dict[str, int] = {}
_lock = threading.Lock()  # protège _last_access et _count_per_domain

# ---------- Models ----------
class SearchResult(BaseModel):
    title: Optional[str]
    url: str
    snippet: Optional[str]
    extract: Optional[str] = None  # petit extrait si follow True
    allowed_by_robots: Optional[bool] = None
    domain: Optional[str] = None

class DeepSearchOut(BaseModel):
    query: str
    results: List[SearchResult]
    meta: Dict[str, Any]

# ---------- Polite helpers ----------
def get_domain(url: str) -> str:
    try:
        p = urlparse(url)
        return p.netloc.lower()
    except Exception:
        return ""

def can_fetch_url(url: str, user_agent: str = USER_AGENT) -> bool:
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
            # si robots.txt non disponible, on choisit la posture prudente : permettre mais avec limites appliquées
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

# ---------- Fetch minimal metadata (title + meta description or first text snippet) ----------
def fetch_metadata(url: str) -> Dict[str, Optional[str]]:
    """
    Récupère en mode poli : title, meta description, extrait court.
    Respecte timeout et user-agent. N'essaie pas d'extraire tout le site.
    """
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    html = resp.text

    # 1) essayer trafilatura (souvent meilleur pour contenu principal)
    try:
        txt = trafilatura.extract(html) or ""
        if txt and len(txt.strip()) > 40:
            # retourner un début lisible
            extract = " ".join(txt.strip().split())[:500]
        else:
            extract = ""
    except Exception:
        extract = ""

    # 2) récupérer title + meta description via BeautifulSoup (rapide)
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    meta = soup.find("meta", attrs={"name":"description"}) or soup.find("meta", attrs={"property":"og:description"})
    snippet = meta.get("content").strip() if meta and meta.get("content") else None

    # fallback snippet to first text excerpt (small)
    if not snippet and not extract:
        # take some visible text
        for sel in ["p", "h1", "h2", "article"]:
            node = soup.find(sel)
            if node and node.get_text(strip=True):
                snippet = node.get_text(strip=True)[:300]
                break

    return {"title": title, "snippet": snippet, "extract": extract}

# ---------- Core: perform search (links from DDG) ----------
def ddg_search_raw(query: str, max_results: int = 50) -> List[Dict]:
    """Retourne la liste brute dicts depuis duckduckgo_search (title, href, body...)."""
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, region="fr-fr", safesearch="moderate", max_results=max_results):
            results.append(r)
    return results

# ---------- Endpoint principal ----------
@app.get("/deep_search", response_model=DeepSearchOut)
def deep_search(
    q: str = Query(..., min_length=2, description="Requête de recherche"),
    max_results: int = Query(DEFAULT_MAX_RESULTS, ge=1, le=200, description="Nombre maximum de résultats (global)"),
    follow: bool = Query(False, description="Si true, on suit chaque lien (poliment) et récupère titre/snippet/extract"),
    max_per_domain: int = Query(DEFAULT_PER_DOMAIN, ge=1, le=50, description="Max pages suivies par domaine"),
    delay_per_domain: float = Query(DEFAULT_DELAY_PER_DOMAIN, ge=0.0, le=10.0, description="Délai minimum (s) entre requêtes sur un même domaine")
):
    # vérifications basiques
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query trop courte")
    max_results = min(max_results, 200)

    # Step 1: obtenir les résultats du moteur (liens)
    try:
        raw = ddg_search_raw(q, max_results=max_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur moteur: {e}")

    results_out: List[SearchResult] = []
    total_followed = 0
    domain_counts_local: Dict[str, int] = {}

    # Step 2: parcourir les résultats, optionnellement suivre
    for r in raw:
        url = r.get("href") or r.get("url")
        title = r.get("title") or None
        snippet_from_search = (r.get("body") or "")[:300] or None
        if not url:
            continue

        domain = get_domain(url)
        allowed = can_fetch_url(url)

        item = SearchResult(
            title=title,
            url=url,
            snippet=snippet_from_search,
            extract=None,
            allowed_by_robots=allowed,
            domain=domain
        )

        # if follow requested and allowed and we haven't exceeded per-domain caps:
        if follow and allowed:
            # per-domain counting
            domain_count = domain_counts_local.get(domain, 0)
            if domain_count >= max_per_domain:
                # skip following this domain further
                item.extract = None
            else:
                # wait politly
                polite_wait(domain, min_interval=delay_per_domain)
                # re-check global/process-level per-domain count
                c = increment_domain_count(domain)
                if c > max_per_domain:
                    # exceeded global process limit for this domain
                    item.extract = None
                else:
                    # attempt fetch metadata, protected by try/except
                    try:
                        meta = fetch_metadata(url)
                        item.title = item.title or meta.get("title")
                        item.snippet = item.snippet or meta.get("snippet")
                        # prefer trafilatura extract if available
                        item.extract = meta.get("extract") or None
                        total_followed += 1
                    except Exception as e:
                        # don't stop the whole pipeline; log in extract
                        item.extract = f"ERROR_FETCH:{str(e)}"
                domain_counts_local[domain] = domain_counts_local.get(domain, 0) + 1

        results_out.append(item)

        # stop early if we've already processed enough raw results (respect max_results)
        if len(results_out) >= max_results:
            break

    meta = {
        "total_results_from_search": len(raw),
        "returned_results": len(results_out),
        "follow_performed": follow,
        "total_followed": total_followed,
        "max_per_domain": max_per_domain,
        "delay_per_domain": delay_per_domain
    }

    return DeepSearchOut(query=q, results=results_out, meta=meta)
