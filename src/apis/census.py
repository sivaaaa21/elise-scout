"""US Census ACS 5-Year client.

Returns market signals for the city a lead's property is in:
    - total_population
    - housing_units
    - renter_occupied_units
    - renter_percentage
    - median_gross_rent
    - median_household_income

Uses the ACS 5-Year Detailed Tables (most recent release) via the public
Census API. The first network call resolves the (state, place) GEO ids from
the city + state strings, the second pulls the actual variables.

Docs: https://www.census.gov/data/developers/data-sets/acs-5year.html
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ACS 5-Year is published with ~2-year lag. 2022 is the latest stable at
# time of writing; the endpoint auto-falls-back if 2022 ever disappears.
ACS_YEAR = 2022
BASE = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"

# Variable IDs (ACS subject table)
VARS = {
    "total_population":        "B01003_001E",
    "housing_units":           "B25001_001E",
    "renter_occupied_units":   "B25003_003E",
    "owner_occupied_units":    "B25003_002E",
    "median_gross_rent":       "B25064_001E",
    "median_household_income": "B19013_001E",
}

# Two-letter state code to FIPS code (contiguous US + DC + PR).
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}


@dataclass
class CensusSnapshot:
    city: str
    state: str
    total_population: Optional[int] = None
    housing_units: Optional[int] = None
    renter_occupied_units: Optional[int] = None
    owner_occupied_units: Optional[int] = None
    renter_percentage: Optional[float] = None
    median_gross_rent: Optional[int] = None
    median_household_income: Optional[int] = None
    source: str = "US Census ACS 5-Year"
    resolved: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _state_fips(state: str) -> Optional[str]:
    if not state:
        return None
    return STATE_FIPS.get(state.strip().upper()[:2])


@lru_cache(maxsize=256)
def _resolve_place(city: str, state_fips: str, api_key: Optional[str]) -> Optional[str]:
    """Resolve a city name within a state to its Census 'place' code.

    The Census 'places' endpoint accepts a NAME filter; we match the
    first place whose name starts with the city we were given.
    """
    params = {
        "get": "NAME",
        "for": f"place:*",
        "in": f"state:{state_fips}",
    }
    if api_key:
        params["key"] = api_key
    try:
        r = requests.get(BASE, params=params, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("Census place lookup failed: %s", e)
        return None

    rows = r.json()[1:]  # row 0 is the header
    needle = city.strip().lower()
    # Prefer exact "city, state" match; fall back to prefix match
    for name, _state, place in rows:
        city_portion = name.split(",")[0].strip().lower()
        if city_portion == needle:
            return place
    for name, _state, place in rows:
        city_portion = name.split(",")[0].strip().lower()
        if city_portion.startswith(needle):
            return place
    return None


def fetch(city: str, state: str, api_key: Optional[str] = None) -> CensusSnapshot:
    """Return a CensusSnapshot for the given city/state.

    Returns an unresolved snapshot (with `resolved=False`) if anything
    fails; callers should treat missing fields as "unknown" rather than
    aborting the whole enrichment.
    """
    api_key = api_key or os.getenv("CENSUS_API_KEY") or None
    snap = CensusSnapshot(city=city, state=state)

    fips = _state_fips(state)
    if not fips:
        log.info("Skipping Census: unknown state '%s'", state)
        return snap

    place = _resolve_place(city, fips, api_key)
    if not place:
        log.info("Skipping Census: no place match for %s, %s", city, state)
        return snap

    var_ids = ",".join(VARS.values())
    params = {
        "get": f"NAME,{var_ids}",
        "for": f"place:{place}",
        "in": f"state:{fips}",
    }
    if api_key:
        params["key"] = api_key

    try:
        r = requests.get(BASE, params=params, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("Census variable fetch failed: %s", e)
        return snap

    data = r.json()
    header, row = data[0], data[1]
    idx = {name: i for i, name in enumerate(header)}

    def _num(var_key: str) -> Optional[int]:
        raw = row[idx[VARS[var_key]]]
        try:
            n = int(raw)
            # Census uses negative sentinels for "N/A"
            return n if n >= 0 else None
        except (TypeError, ValueError):
            return None

    snap.total_population        = _num("total_population")
    snap.housing_units           = _num("housing_units")
    snap.renter_occupied_units   = _num("renter_occupied_units")
    snap.owner_occupied_units    = _num("owner_occupied_units")
    snap.median_gross_rent       = _num("median_gross_rent")
    snap.median_household_income = _num("median_household_income")

    occupied = (snap.renter_occupied_units or 0) + (snap.owner_occupied_units or 0)
    if occupied > 0 and snap.renter_occupied_units is not None:
        snap.renter_percentage = round(100 * snap.renter_occupied_units / occupied, 1)

    snap.resolved = True
    return snap
