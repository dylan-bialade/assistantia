from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class SearchResult(BaseModel):
    title: Optional[str]
    url: str
    snippet: Optional[str]
    extract: Optional[str] = None
    allowed_by_robots: Optional[bool] = None
    domain: Optional[str] = None
    score: Optional[float] = None  # <-- important

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
    strict_block: Optional[bool] = False
