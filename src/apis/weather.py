"""OpenWeather client. Used purely as an icebreaker in the email opener.

Uses the free `/data/2.5/weather` endpoint. We do a geocoding call first
so we don't accidentally match the wrong "Springfield".
Docs: https://openweathermap.org/current
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict
from typing import Optional

import requests

log = logging.getLogger(__name__)

GEO = "https://api.openweathermap.org/geo/1.0/direct"
CURRENT = "https://api.openweathermap.org/data/2.5/weather"


@dataclass
class WeatherSnapshot:
    city: str
    state: str
    temperature_f: Optional[float] = None
    conditions: Optional[str] = None
    description: Optional[str] = None
    resolved: bool = False
    source: str = "OpenWeather"

    def as_dict(self) -> dict:
        return asdict(self)


def fetch(city: str, state: str, country: str = "US", api_key: Optional[str] = None) -> WeatherSnapshot:
    api_key = api_key or os.getenv("OPENWEATHER_API_KEY") or None
    snap = WeatherSnapshot(city=city, state=state)

    if not api_key:
        log.info("Skipping OpenWeather: no OPENWEATHER_API_KEY set")
        return snap

    try:
        geo_r = requests.get(GEO, params={
            "q": f"{city},{state},{country}", "limit": 1, "appid": api_key,
        }, timeout=10)
        geo_r.raise_for_status()
        geo = geo_r.json()
    except requests.RequestException as e:
        log.info("OpenWeather geocode failed for %s, %s: %s", city, state, e)
        return snap

    if not geo:
        return snap

    lat, lon = geo[0]["lat"], geo[0]["lon"]
    try:
        w = requests.get(CURRENT, params={
            "lat": lat, "lon": lon, "units": "imperial", "appid": api_key,
        }, timeout=10)
        w.raise_for_status()
        data = w.json()
    except requests.RequestException as e:
        log.info("OpenWeather current failed for %s, %s: %s", city, state, e)
        return snap

    snap.temperature_f = data.get("main", {}).get("temp")
    weather = (data.get("weather") or [{}])[0]
    snap.conditions = weather.get("main")
    snap.description = weather.get("description")
    snap.resolved = snap.temperature_f is not None
    return snap
