"""Wikipedia client. Pulls quick company context for the email opener.

Uses the REST v1 `page/summary` endpoint, which returns a short extract
and some structural info. No API key required.
Docs: https://en.wikipedia.org/api/rest_v1/
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)

SEARCH = "https://en.wikipedia.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary"

HEADERS = {
    # Wikipedia asks for a descriptive UA
    "User-Agent": "EliseAI-Lead-Enricher/1.0 (https://eliseai.com; gtm@example.com)"
}

# Corporate boilerplate to strip before matching. These words show up in
# almost every property-mgmt company name and shouldn't drive the match.
GENERIC_COMPANY_TERMS = {
    "inc", "llc", "ltd", "corp", "corporation", "company", "co",
    "group", "holdings", "partners", "properties", "property",
    "management", "mgmt", "realty", "trust", "services",
    "international", "communities", "residential", "apartments",
    "homes", "estates", "realtors", "capital", "ventures",
    "the", "and", "of",
}

# Domain-relevance guard: the Wikipedia page must actually be about real
# estate, multifamily, or property management. If a company name collides
# with a singer, racehorse, or hospital, we'd rather return nothing than
# drop the wrong context into an outreach email.
DOMAIN_KEYWORDS = (
    "real estate", "real-estate", "reit",
    "property", "properties", "propertymanagement",
    "apartment", "apartments", "multifamily", "multi-family",
    "rental", "rentals", "leasing", "lease",
    "housing", "residential", "residences", "residence",
    "landlord", "tenant",
    "homebuilder", "home builder", "developer", "development",
    "condominium", "condo",
)


def _is_relevant_to_domain(description: Optional[str], extract: Optional[str]) -> bool:
    """Returns True if the page looks like real estate or property mgmt."""
    blob = f"{description or ''} {extract or ''}".lower()
    return any(kw in blob for kw in DOMAIN_KEYWORDS)


@dataclass
class WikipediaSnapshot:
    company: str
    title: Optional[str] = None
    description: Optional[str] = None
    extract: Optional[str] = None
    url: Optional[str] = None
    resolved: bool = False
    source: str = "Wikipedia"

    def as_dict(self) -> dict:
        return asdict(self)


def _is_confident_match(company: str, title: str) -> bool:
    """Return True if the company name appears as a contiguous phrase in title.

    This is intentionally strict. For SDR outreach, no context is better
    than wrong context: matching "Lincoln Property Company" to the Lincoln
    car brand would produce embarrassing email copy.

    Match rules:
      1. Reject any title with a comma. Wikipedia uses commas for places
         ("Pinebrook, NY") and disambiguated people ("Smith, John"), and
         almost never for companies.
      2. The company name must appear as a contiguous, word-bounded
         substring of the title. Trailing generic suffixes can be stripped
         first (so "Smalltown Properties LLC" can match "Smalltown
         Properties"), as long as at least one non-generic token remains.
    """
    if "," in title:
        return False

    title_norm = re.sub(r"\s+", " ", title.strip()).lower()
    tokens = re.findall(r"[A-Za-z]+", company)
    original_len = len(tokens)
    # Multi-word companies must still match on >=2 contiguous tokens after
    # stripping; otherwise "Lincoln Property Company" happily matches
    # "Lincoln Motor Company" on the word "Lincoln" alone.
    min_len = 2 if original_len >= 2 else 1

    while len(tokens) >= min_len:
        remaining = [t for t in tokens if t.lower() not in GENERIC_COMPANY_TERMS]
        if not remaining:
            return False  # nothing distinctive left, refuse to match
        candidate = " ".join(tokens).lower()
        if re.search(r"\b" + re.escape(candidate) + r"\b", title_norm):
            return True
        # Strip a trailing generic term and try again
        if tokens[-1].lower() in GENERIC_COMPANY_TERMS:
            tokens = tokens[:-1]
            continue
        break
    return False


def _search_title(company: str) -> Optional[str]:
    """Find a Wikipedia page whose title confidently matches the company.

    Pulls the top few search results (not just the top one) and walks them
    in order, returning the first one that passes the confidence check.
    Returns None if none of them pass.
    """
    params = {
        "action": "query",
        "list": "search",
        "srsearch": company,
        "srlimit": 5,
        "format": "json",
    }
    try:
        r = requests.get(SEARCH, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        log.info("Wikipedia search failed for %s: %s", company, e)
        return None

    results = r.json().get("query", {}).get("search", [])
    for hit in results:
        title = hit.get("title", "")
        if _is_confident_match(company, title):
            return title

    log.info("Wikipedia: no confident match for '%s' (top hits: %s)",
             company, [h.get("title") for h in results[:3]])
    return None


def fetch(company: str) -> WikipediaSnapshot:
    """Return a Wikipedia summary for the given company, if one exists."""
    snap = WikipediaSnapshot(company=company)
    title = _search_title(company)
    if not title:
        return snap

    try:
        r = requests.get(f"{SUMMARY}/{quote(title)}", headers=HEADERS, timeout=10)
        if r.status_code == 404:
            return snap
        r.raise_for_status()
    except requests.RequestException as e:
        log.info("Wikipedia summary failed for %s: %s", title, e)
        return snap

    data = r.json()
    # Skip disambiguation pages. Too noisy to use in outreach.
    if data.get("type") == "disambiguation":
        return snap

    description = data.get("description")
    extract = data.get("extract")
    # Final guard: even if the name matched, the page has to be in our
    # domain. Catches false positives like "Bayview Management" resolving
    # to "Annaly Capital Management", or same-named singers/racehorses.
    if not _is_relevant_to_domain(description, extract):
        log.info("Wikipedia: rejecting '%s' → '%s' (off-domain: %s)",
                 company, data.get("title"), description)
        return snap

    snap.title = data.get("title")
    snap.description = description
    snap.extract = extract
    snap.url = (data.get("content_urls", {}).get("desktop", {}) or {}).get("page")
    snap.resolved = bool(snap.extract)
    return snap
