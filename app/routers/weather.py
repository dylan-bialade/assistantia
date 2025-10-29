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
