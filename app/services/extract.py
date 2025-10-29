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
