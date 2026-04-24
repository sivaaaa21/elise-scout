"""CSV input/output helpers."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional

import pandas as pd


REQUIRED_COLUMNS = ["name", "email", "company", "property_address", "city", "state"]


@dataclass
class Lead:
    name: str
    email: str
    company: str
    property_address: str
    city: str
    state: str
    country: str = "US"


@dataclass
class EnrichedLeadRow:
    """One row in the enriched output (CSV or Sheets)."""
    name: str
    email: str
    company: str
    property_address: str
    city: str
    state: str
    country: str
    score: int
    tier: str
    component_market_size: int
    component_rental_mix: int
    component_rent_level: int
    component_company_signal: int
    market_population: Optional[int]
    market_renter_percentage: Optional[float]
    market_median_rent: Optional[int]
    market_median_income: Optional[int]
    wikipedia_description: Optional[str]
    wikipedia_url: Optional[str]
    top_news_title: Optional[str]
    top_news_url: Optional[str]
    top_news_source: Optional[str]
    top_news_date: Optional[str]
    weather_description: Optional[str]
    weather_temp_f: Optional[float]
    email_subject: str
    email_body: str
    email_provider: str
    insights: str  # newline-joined
    enriched_at: str

    def as_dict(self) -> dict:
        return asdict(self)


def read_leads(path: str) -> List[Lead]:
    df = pd.read_csv(path, dtype=str).fillna("")
    # Normalize column names: lowercase, underscores
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Input CSV is missing required columns: {missing}. "
            f"Found: {list(df.columns)}"
        )

    leads = []
    for _, row in df.iterrows():
        leads.append(Lead(
            name=row["name"].strip(),
            email=row["email"].strip(),
            company=row["company"].strip(),
            property_address=row["property_address"].strip(),
            city=row["city"].strip(),
            state=row["state"].strip(),
            country=(row["country"].strip() if "country" in df.columns and row["country"] else "US"),
        ))
    return leads


def write_enriched(rows: List[EnrichedLeadRow], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([r.as_dict() for r in rows])
    df.to_csv(path, index=False)
