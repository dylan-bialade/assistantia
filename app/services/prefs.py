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
        "strict_block": bool(row["strict_block"]) if "strict_block" in row.keys() else False,  # <--- AJOUT
    }

def is_hard_block(domain: str, url: str, prefs: dict, fb_counts) -> bool:
    """Retourne True si on DOIT cacher le résultat en mode strict."""
    if domain in (prefs.get("blocked_domains") or set()):
        return True
    likes_domain, dislikes_domain, likes_url, dislikes_url = fb_counts
    # si URL dislikée au moins 1x -> on bloque
    if dislikes_url.get(url, 0) > 0:
        return True
    # si domaine massivement disliké -> on bloque aussi
    if dislikes_domain.get(domain, 0) > 0:
        return True
    return False


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
