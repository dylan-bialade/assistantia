# ===== setup.ps1 — installe et prépare le projet assistantia =====
param(
  [string]$Root = "C:\Users\dylan\assistantia",
  [int]$Port = 8002
)

Write-Host ">> Création du projet dans $Root"

# --- 0) Dossier propre ---
if (!(Test-Path $Root)) { New-Item -ItemType Directory -Path $Root | Out-Null }
Set-Location $Root

# --- 1) Créer venv propre ---
# essaie py, sinon python
$python = ""
try { $v = (& py --version) 2>$null; if ($LASTEXITCODE -eq 0) { $python = "py" } } catch {}
if (-not $python) {
  try { $v = (& python --version) 2>$null; if ($LASTEXITCODE -eq 0) { $python = "python" } } catch {}
}
if (-not $python) { throw "Python non trouvé. Installe Python 3.11+ depuis https://www.python.org/downloads/ puis relance." }

if (Test-Path ".\.venv") { Write-Host ">> venv déjà présent" } else {
  if ($python -eq "py") { & py -3.11 -m venv .venv } else { & python -m venv .venv }
}

# --- 2) Activer venv ---
$envPath = Join-Path $Root ".venv\Scripts\Activate.ps1"
. $envPath

# --- 3) Dossier code ---
if (!(Test-Path ".\app")) { New-Item -ItemType Directory -Path ".\app" | Out-Null }
Set-Location ".\app"

# --- 4) requirements.txt ---
@"
fastapi
uvicorn
pydantic
duckduckgo-search
trafilatura
requests
beautifulsoup4
watchfiles
"@ | Set-Content -Encoding UTF8 ..\requirements.txt

# --- 5) Installer dépendances ---
python -m pip install --upgrade pip
pip install -r ..\requirements.txt

# --- 6) server_min.py (smoke test) ---
@"
from fastapi import FastAPI
print('>>> LOADED (min):', __file__)
app = FastAPI(title='Smoke Test')
@app.get('/')
def root():
    return {'ok': True, 'msg': 'root ok'}
@app.get('/routes')
def routes():
    return [r.path for r in app.router.routes]
"@ | Set-Content -Encoding UTF8 .\server_min.py

# --- 7) server.py (app complète) ---
@"
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Optional
import requests, time
from duckduckgo_search import DDGS
import trafilatura
from bs4 import BeautifulSoup

print('>>> LOADED:', __file__)  # debug
USER_NAME = 'Dylan'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36'}

WEATHER_DESC = {
    0:'ciel dégagé',1:'peu nuageux',2:'partiellement nuageux',3:'couvert',
    45:'brouillard',48:'brouillard givrant',51:'bruine faible',53:'bruine modérée',55:'bruine forte',
    56:'bruine verglaçante faible',57:'bruine verglaçante forte',
    61:'pluie faible',63:'pluie modérée',65:'pluie forte',66:'pluie verglaçante faible',67:'pluie verglaçante forte',
    71:'neige faible',73:'neige modérée',75:'neige forte',77:'neige en grains',
    80:'averses faibles',81:'averses modérées',82:'averses fortes',85:'averses de neige faibles',86:'averses de neige fortes',
    95:'orages',96:'orages avec grêle faible',99:'orages avec grêle forte'
}
def describe_weather(code: Optional[int]) -> str:
    return WEATHER_DESC.get(code, f'code météo {code}' if code is not None else 'conditions inconnues')

app = FastAPI(title='Assistant de Dylan')

class ChatIn(BaseModel):
    message: str
class ChatOut(BaseModel):
    reply: str

@app.get('/')
def root():
    return {'ok': True, 'msg': f'Bonjour {USER_NAME}, l’API est prête.'}
@app.get('/routes')
def routes():
    return [r.path for r in app.router.routes]
@app.post('/chat', response_model=ChatOut)
def chat(inp: ChatIn):
    return ChatOut(reply=f'Bonjour {USER_NAME} 👋 Tu as dit : “{inp.message}”.')

# ---- extraction robuste ----
def extract_with_bs4(html: str, max_chars: int = 1600) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script','style','noscript']): tag.decompose()
    text = ' '.join(soup.get_text(separator=' ').split())
    return text[:max_chars]
def fetch_page_text(url: str, timeout: int = 8, max_chars: int = 1600) -> str:
    try:
        downloaded = trafilatura.fetch_url(url, timeout=timeout)
        if downloaded:
            txt = trafilatura.extract(downloaded) or ''
            if txt.strip(): return txt.strip()[:max_chars]
    except Exception: pass
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.ok and resp.text:
            txt = trafilatura.extract(resp.text) or ''
            if txt.strip(): return txt.strip()[:max_chars]
            return extract_with_bs4(resp.text, max_chars=max_chars)
    except Exception: pass
    return ''

# ---- recherche web ----
@app.get('/web_fast')
def web_fast(q: str = 'tendances IA en entreprise 2025', max_results: int = 3):
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(q, region='fr-fr', safesearch='moderate', max_results=max_results):
                url = r.get('href') or r.get('url')
                if url: results.append({'title': r.get('title') or 'Résultat', 'url': url})
    except Exception as e:
        return {'query': q, 'error': str(e), 'results': results}
    return {'query': q, 'results': results}
def web_search(query: str, max_results: int = 3) -> List[Dict]:
    out: List[Dict] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, region='fr-fr', safesearch='moderate', max_results=max_results):
                url = r.get('href') or r.get('url')
                if not url: continue
                extract = fetch_page_text(url, timeout=8, max_chars=1400)
                out.append({'title': r.get('title') or 'Résultat', 'url': url, 'snippet': (r.get('body') or '')[:220], 'extract': extract})
                time.sleep(0.4)
    except Exception as e:
        out.append({'title':'ERREUR','url':'','snippet':str(e),'extract':''})
    return out
@app.get('/web_test')
def web_test(q: str = 'site:wikipedia.org intelligence artificielle', max_results: int = 2):
    return {'query': q, 'results': web_search(q, max_results=max_results)}

# ---- météo (Open-Meteo) ----
def geocode_city(city: str) -> Dict:
    url = 'https://geocoding-api.open-meteo.com/v1/search'
    params = {'name': city, 'count': 1, 'language': 'fr', 'format': 'json'}
    r = requests.get(url, params=params, headers=HEADERS, timeout=8); r.raise_for_status()
    data = r.json(); results = data.get('results') or []
    if not results: raise ValueError(f'Ville introuvable: {city}')
    top = results[0]
    return {'lat': top['latitude'], 'lon': top['longitude'], 'name': top.get('name'), 'admin1': top.get('admin1'), 'country': top.get('country')}
def open_meteo_tomorrow(lat: float, lon: float) -> Dict:
    url = ('https://api.open-meteo.com/v1/forecast'
           f'?latitude={lat}&longitude={lon}'
           '&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode'
           '&timezone=Europe%2FParis')
    r = requests.get(url, headers=HEADERS, timeout=8); r.raise_for_status()
    return r.json()
@app.get('/weather')
def weather(city: str = 'Castres'):
    loc = geocode_city(city)
    data = open_meteo_tomorrow(loc['lat'], loc['lon'])
    daily = data.get('daily', {})
    def pick(i, key, default=None):
        arr = daily.get(key) or []
        return arr[i] if len(arr) > i else default
    tmax = pick(1,'temperature_2m_max'); tmin = pick(1,'temperature_2m_min')
    prcp = pick(1,'precipitation_sum'); code = pick(1,'weathercode')
    return {'city': f"{loc['name']}, {loc['admin1']}, {loc['country']}",
            'coords': {'lat': loc['lat'], 'lon': loc['lon']},
            'tomorrow': {'tmin_c': tmin, 'tmax_c': tmax, 'precipitation_mm': prcp,
                         'weathercode': code, 'description': describe_weather(code)}}
"@ | Set-Content -Encoding UTF8 .\server.py

# --- 8) run.bat pour lancer facilement ---
Set-Location $Root
@"
@echo off
setlocal
cd /d %~dp0
call .\.venv\Scripts\activate
cd app
python -m uvicorn server:app --reload --port $Port --reload-include *.py --reload-exclude ""..\.venv""
endlocal
"@ | Set-Content -Encoding UTF8 .\run.bat

Write-Host ""
Write-Host ">> Installation terminée."
Write-Host "----------------------------------------"
Write-Host "Pour lancer ton serveur :"
Write-Host "  1) Double-clique sur run.bat"
Write-Host "  2) Ou exécute cette commande dans PowerShell :"
Write-Host "       .\run.bat"
Write-Host "----------------------------------------"
