"""NewsAPI client. Fetches recent mentions of a lead's company.

Uses the `/v2/everything` endpoint. Free tier permits up to 100 requests
per day, which is enough for a daily SDR batch.
Docs: https://newsapi.org/docs/endpoints/everything
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

import requests

log = logging.getLogger(__name__)

BASE = "https://newsapi.org/v2/everything"

# Same generic-suffix list used by the Wikipedia matcher. A one-word
# company like "Greystar" must appear literally; multi-word names get
# their trailing generics stripped so "Lincoln Property Company" is
# checked as "Lincoln Property".
GENERIC_COMPANY_TERMS = {
    "inc", "llc", "ltd", "corp", "corporation", "company", "co",
    "group", "holdings", "partners", "properties", "property",
    "management", "mgmt", "realty", "trust", "services",
    "international", "communities", "residential", "apartments",
    "homes", "estates", "realtors", "capital", "ventures",
    "the", "and", "of",
}


def _distinctive_phrase(company: str) -> str:
    """Strip trailing generic suffixes, keep the rest as a phrase.

    'Lincoln Property Company' → 'lincoln property'
    'Greystar'                 → 'greystar'
    'Bell Partners'            → 'bell'  (would be rejected below)
    """
    tokens = re.findall(r"[A-Za-z]+", company)
    while tokens and tokens[-1].lower() in GENERIC_COMPANY_TERMS:
        tokens = tokens[:-1]
    return " ".join(tokens).lower()


def _article_mentions_company(article_title: str, article_desc: str, company: str) -> bool:
    """Returns True if the article is actually about the company.

    NewsAPI returns a hit any time the company name shows up anywhere in
    the full article body, which leaks in articles that only mention the
    company in passing. We apply two checks:

      1. The company name must appear in the headline. The SDR will paste
         this into an email, so it has to read as relevant at a glance.
      2. The company name must appear at least twice across title and
         description combined. One mention could be incidental; two is a
         reliable signal the piece is genuinely about them.

    Titles truncated by NewsAPI (ending in "..." or "…") get a softer
    treatment: a description match alone will carry them through, since
    the full title was probably rich enough but got cut off.
    """
    phrase = _distinctive_phrase(company)
    # Single-token leftovers like 'bell' or 'lincoln' are too ambiguous
    # on their own. Only accept them if the original company was a
    # single word to start with (e.g. 'Greystar', 'AvalonBay').
    original_tokens = re.findall(r"[A-Za-z]+", company)
    is_multiword = " " in phrase
    is_single_word_company = len(original_tokens) == 1
    if not phrase or (not is_multiword and not is_single_word_company):
        return False

    pattern = re.compile(r"\b" + re.escape(phrase) + r"\b")
    title_l = (article_title or "").lower()
    desc_l = (article_desc or "").lower()
    title_hits = len(pattern.findall(title_l))
    desc_hits = len(pattern.findall(desc_l))
    total_hits = title_hits + desc_hits

    # Check 1: headline must name the company (with a fallback for truncated titles)
    title_ok = title_hits > 0 or (
        (title_l.endswith("...") or title_l.endswith("…")) and desc_hits > 0
    )
    # Check 2: at least two mentions total across title + description
    focus_ok = total_hits >= 2

    return title_ok and focus_ok


@dataclass
class NewsArticle:
    title: str
    url: str
    source: str
    published_at: str
    description: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class NewsSnapshot:
    company: str
    articles: List[NewsArticle] = field(default_factory=list)
    total_results: int = 0
    resolved: bool = False
    source: str = "NewsAPI"

    @property
    def has_recent_news(self) -> bool:
        return self.total_results > 0

    @property
    def headline_hook(self) -> Optional[str]:
        """Return the freshest headline, if any, for email personalization."""
        return self.articles[0].title if self.articles else None

    def as_dict(self) -> dict:
        return {
            "company": self.company,
            "total_results": self.total_results,
            "resolved": self.resolved,
            "source": self.source,
            "articles": [a.as_dict() for a in self.articles],
        }


def fetch(company: str, api_key: Optional[str] = None, max_articles: int = 3) -> NewsSnapshot:
    """Return the most recent English-language articles mentioning `company`."""
    api_key = api_key or os.getenv("NEWSAPI_KEY") or None
    snap = NewsSnapshot(company=company)

    if not api_key:
        log.info("Skipping NewsAPI: no NEWSAPI_KEY set")
        return snap

    # Quoted search keeps multi-word company names together.
    # Over-fetch so the post-filter has room to discard off-topic hits
    # without leaving us with zero articles.
    params = {
        "q": f'"{company}"',
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": max(max_articles * 4, 10),
        "apiKey": api_key,
    }
    try:
        r = requests.get(BASE, params=params, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("NewsAPI fetch failed for %s: %s", company, e)
        return snap

    payload = r.json()
    if payload.get("status") != "ok":
        log.warning("NewsAPI error for %s: %s", company, payload.get("message"))
        return snap

    raw_articles = payload.get("articles", [])
    kept, dropped = [], []
    for item in raw_articles:
        title = (item.get("title") or "").strip()
        desc = (item.get("description") or "").strip()
        if not _article_mentions_company(title, desc, company):
            dropped.append(title[:70])
            continue
        kept.append(NewsArticle(
            title=title,
            url=item.get("url", ""),
            source=(item.get("source") or {}).get("name", ""),
            published_at=item.get("publishedAt", ""),
            description=desc,
        ))
        if len(kept) >= max_articles:
            break

    if dropped:
        log.info("NewsAPI: dropped %d off-topic article(s) for '%s' (e.g. %s)",
                 len(dropped), company, dropped[:2])

    snap.total_results = len(kept)
    snap.articles = kept
    snap.resolved = bool(kept)
    return snap
