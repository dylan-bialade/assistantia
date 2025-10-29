import os, json, time, threading
from typing import List, Dict, Optional
from urllib.parse import urlparse
from urllib import robotparser
from app.neurone.nn_personalizer import personalizer_predict
import requests
import trafilatura
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from typing import Optional
# Moteurs de recherche
try:
    from ddgs import DDGS
except Exception:
    from duckduckgo_search import DDGS
from googlesearch import search

# Similarité / mémoire (GPU si dispo)
import torch
from sentence_transformers import SentenceTransformer, util

HEADERS = {"User-Agent": "AssistantDylan/1.0 (+https://example.local)"}
REQUEST_TIMEOUT = 8
DEFAULT_MAX_RESULTS = 50
DEFAULT_DELAY_PER_DOMAIN = 1.0

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "user_prefs.json")

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🧠 Similarité sur {device.upper()}")
model = SentenceTransformer("all-MiniLM-L6-v2", device=device)

_lock = threading.Lock()
_last_access: Dict[str, float] = {}
_robots_cache: Dict[str, Optional[robotparser.RobotFileParser]] = {}

class SearchResult:
    def __init__(self, title=None, url=None, snippet=None, extract=None, allowed_by_robots=None, domain=None, score=0.0):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.extract = extract
        self.allowed_by_robots = allowed_by_robots
        self.domain = domain
        self.score = score

# ---------- JSON utils ----------
def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {"preferences": {"boost": [], "ban": []}, "history": []}
    with open(path, "r", encoding="utf8") as f:
        return json.load(f)

def save_json(path: str, data: dict):
    with open(path, "w", encoding="utf8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def score_result(item, query, prefs, fb_counts, base_rank=0, w_text=1.0, w_domain=0.2, w_recency=0.1, w_nn=0.7):
    """
    Ajoute le score du réseau neuronal (w_nn * proba_like) dans la note finale.
    """
    text_bits = " ".join(filter(None, [item.title or "", item.snippet or "", item.url or ""]))
    # Score NN ∈ [0,1]
    nn_score = personalizer_predict(text_bits)

    # ... tes anciens signaux (texte, domaine, fraicheur, etc.)
    classical = 0.0
    # classical += ...  # garde ton calcul existant

    final = classical + (w_nn * nn_score)
    item.personal_score = nn_score  # pour debug/affichage
    item.score = final              # si ton modèle Pydantic le permet, sinon utiliser setattr type-safe
    return final

# ---------- Réseau / parsing ----------
def get_domain(url: str) -> str:
    try: return urlparse(url).netloc.lower()
    except: return ""

def can_fetch_url(url: str) -> bool:
    domain = get_domain(url)
    if not domain: return False
    base = f"{urlparse(url).scheme}://{domain}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = robotparser.RobotFileParser()
        try:
            rp.set_url(base + "/robots.txt"); rp.read(); _robots_cache[base] = rp
        except Exception:
            _robots_cache[base] = None; return True
    if rp is None: return True
    return rp.can_fetch(HEADERS["User-Agent"], url)

def polite_wait(domain: str, min_interval: float = DEFAULT_DELAY_PER_DOMAIN):
    with _lock:
        last = _last_access.get(domain); now = time.time()
        if last:
            wait = min_interval - (now - last)
            if wait > 0: time.sleep(wait)
        _last_access[domain] = time.time()

def fetch_page_text(url: str, timeout: int = 8, max_chars: int = 1600) -> str:
    try:
        downloaded = trafilatura.fetch_url(url, timeout=timeout)
        if downloaded:
            txt = trafilatura.extract(downloaded) or ""
            if txt.strip(): return txt.strip()[:max_chars]
    except Exception: pass
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.ok and resp.text:
            txt = trafilatura.extract(resp.text) or ""
            if txt.strip(): return txt.strip()[:max_chars]
            soup = BeautifulSoup(resp.text, "html.parser")
            for t in soup(["script","style","noscript"]): t.decompose()
            return " ".join(soup.get_text(separator=" ").split())[:max_chars]
    except Exception: pass
    return ""

# ---------- Moteurs ----------
def google_search_raw(query: str, max_results: int = 30):
    try:
        urls = list(search(query, num_results=max_results, lang="fr"))
        return [{"title": None, "href": u, "body": ""} for u in urls]
    except Exception as e:
        print(f"[google] ⚠️ {e}")
        return []

def ddg_search_raw(query: str, max_results: int = 30):
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, region="fr-fr", safesearch="moderate", max_results=max_results))
    except Exception as e:
        print(f"[ddg] ⚠️ {e}")
        return []

def hybrid_search(query: str, max_results: int = 30):
    g = google_search_raw(query, max_results=max_results//2)
    d = ddg_search_raw(query, max_results=max_results//2)
    seen, out = set(), []
    for r in g + d:
        url = r.get("href") or r.get("url")
        if url and url not in seen:
            seen.add(url); out.append(r)
    return out

# ---------- Feedback / préférences ----------
def record_feedback(url: str, liked: bool):
    data = load_json(DB_PATH)
    prefs = data.setdefault("preferences", {"boost": [], "ban": []})
    dom = get_domain(url)
    if liked:
        if dom not in prefs["boost"]: prefs["boost"].append(dom)
    else:
        if dom not in prefs["ban"]: prefs["ban"].append(dom)
    save_json(DB_PATH, data)

def apply_preferences(results: List[SearchResult]) -> List[SearchResult]:
    data = load_json(DB_PATH)
    boost = set(data.get("preferences", {}).get("boost", []))
    ban = set(data.get("preferences", {}).get("ban", []))
    out = []
    for it in results:
        d = it.domain or ""
        if any(b in d for b in ban):  # filtre dur
            continue
        if any(b in d for b in boost):
            it.score += 2.0
        out.append(it)
    return out

# ---------- Similarité : filtrer ce qui ressemble aux dislikes ----------
def filter_by_similarity(results: List[SearchResult]) -> List[SearchResult]:
    data = load_json(DB_PATH)
    dislikes = [ (h.get("title","") + " " + h.get("snippet","")).strip()
                 for h in data.get("history", []) if h.get("liked") is False ]
    dislikes = [t for t in dislikes if t]
    if not dislikes:
        return results
    # Embeddings GPU/CPU
    dislike_vecs = model.encode(dislikes, convert_to_tensor=True)  # [N, D]
    kept = []
    for it in results:
        text = ((it.title or "") + " " + (it.snippet or "")).strip()
        if not text:
            kept.append(it); continue
        v = model.encode([text], convert_to_tensor=True)  # [1, D]
        sim = float(util.max_sim(v1=v, v2=dislike_vecs))
        if sim < 0.7:  # seuil de similarité
            kept.append(it)
    return kept

# ---------- Rerank général ----------
def rerank(results: List[SearchResult], query: str) -> List[SearchResult]:
    results = apply_preferences(results)
    results = filter_by_similarity(results)
    # tri par score décroissant
    results.sort(key=lambda x: x.score, reverse=True)
    # Historique (best effort)
    try:
        data = load_json(DB_PATH)
        for it in results[:30]:
            data["history"].append({
                "query": query,
                "title": it.title,
                "snippet": it.snippet,
                "url": it.url,
                "domain": it.domain,
                "liked": None,  # sera rempli si tu cliques 👍/👎
                "ts": time.time()
            })
        save_json(DB_PATH, data)
    except Exception:
        pass
    return results

# ---------- Build enrichi ----------
def follow_and_build(raw: List[Dict], follow=False, max_per_domain=5, delay_per_domain=1.0) -> List[SearchResult]:
    out: List[SearchResult] = []
    counts: Dict[str, int] = {}
    for r in raw:
        url = r.get("href") or r.get("url")
        if not url: continue
        dom = get_domain(url)
        ok = can_fetch_url(url)
        it = SearchResult(
            title=r.get("title") or url,
            url=url,
            snippet=(r.get("body") or "")[:300],
            extract=None,
            allowed_by_robots=ok,
            domain=dom,
            score=0.0
        )
        if follow and ok:
            if counts.get(dom, 0) < max_per_domain:
                polite_wait(dom, delay_per_domain)
                it.extract = fetch_page_text(url)
                counts[dom] = counts.get(dom, 0) + 1
        out.append(it)
        if len(out) >= DEFAULT_MAX_RESULTS: break
    return out
