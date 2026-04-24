"""EliseAI inbound-lead enricher. CLI entry point.

Examples:
    # CSV in, CSV out (default)
    python -m src.enricher --input data/leads_sample.csv --output output/enriched_leads.csv

    # Google Sheets on both ends
    python -m src.enricher --source sheets --sink sheets

    # Read CSV, push to Sheets
    python -m src.enricher --input data/leads_sample.csv --sink sheets

Loads environment variables from .env if present. See .env.example.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import List

from dotenv import load_dotenv

from .apis import census as census_api
from .apis import news as news_api
from .apis import weather as weather_api
from .apis import wikipedia as wiki_api
from .email_gen import generate as generate_email
from .io_csv import EnrichedLeadRow, Lead, read_leads as read_csv_leads, write_enriched as write_csv
from .scoring import build_insights, score as score_lead


log = logging.getLogger("enricher")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Keep requests/urllib quiet
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _enrich_one(lead: Lead) -> EnrichedLeadRow:
    log.info("Enriching %s @ %s (%s, %s)", lead.name, lead.company, lead.city, lead.state)

    # Sequential API calls. Rate limits, not latency, are the bottleneck
    # here, so async wouldn't help much until batches get a lot bigger.
    census = census_api.fetch(lead.city, lead.state)
    news   = news_api.fetch(lead.company)
    wiki   = wiki_api.fetch(lead.company)
    weather = weather_api.fetch(lead.city, lead.state, lead.country)

    score_obj = score_lead(census, news, wiki)
    insights = build_insights(
        lead.name, lead.company, lead.city, lead.state,
        census, news, wiki, score_obj, weather,
    )
    email = generate_email(
        lead.name, lead.company, lead.city, lead.state,
        census, news, wiki, weather, score_obj,
    )

    top_news = news.articles[0] if news.articles else None

    return EnrichedLeadRow(
        name=lead.name,
        email=lead.email,
        company=lead.company,
        property_address=lead.property_address,
        city=lead.city,
        state=lead.state,
        country=lead.country,
        score=score_obj.total,
        tier=score_obj.tier,
        component_market_size=score_obj.component_market_size,
        component_rental_mix=score_obj.component_rental_mix,
        component_rent_level=score_obj.component_rent_level,
        component_company_signal=score_obj.component_company_signal,
        market_population=census.total_population,
        market_renter_percentage=census.renter_percentage,
        market_median_rent=census.median_gross_rent,
        market_median_income=census.median_household_income,
        wikipedia_description=wiki.description,
        wikipedia_url=wiki.url,
        top_news_title=top_news.title if top_news else None,
        top_news_url=top_news.url if top_news else None,
        top_news_source=top_news.source if top_news else None,
        top_news_date=top_news.published_at if top_news else None,
        weather_description=weather.description,
        weather_temp_f=weather.temperature_f,
        email_subject=email.subject,
        email_body=email.body,
        email_provider=email.provider,
        insights="\n".join(insights),
        enriched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _print_summary(rows: List[EnrichedLeadRow]) -> None:
    if not rows:
        print("No leads processed.")
        return
    rows_by_score = sorted(rows, key=lambda r: -r.score)
    width = max((len(r.company) for r in rows_by_score), default=10)
    print("\n=== Lead Enrichment Summary ===")
    print(f"{'Score':>5}  {'Tier':<4}  {'Company'.ljust(width)}  City, State")
    print("-" * (20 + width))
    for r in rows_by_score:
        print(f"{r.score:>5}  {r.tier:<4}  {r.company.ljust(width)}  {r.city}, {r.state}")
    # Tier distribution
    dist = {}
    for r in rows:
        dist[r.tier] = dist.get(r.tier, 0) + 1
    print("\nTier distribution:", ", ".join(f"{k}: {v}" for k, v in dist.items()))
    print("\nTop lead's draft email:")
    top = rows_by_score[0]
    print(f"  Subject: {top.email_subject}")
    print("  Body:")
    for line in top.email_body.splitlines():
        print(f"    {line}")


def main(argv=None) -> int:
    load_dotenv()  # .env is optional; no-op if absent

    parser = argparse.ArgumentParser(description="Enrich and score EliseAI inbound leads.")
    parser.add_argument("--source", choices=["csv", "sheets"], default="csv",
                        help="Where to read leads from (default: csv)")
    parser.add_argument("--sink", choices=["csv", "sheets", "both"], default="csv",
                        help="Where to write enriched output (default: csv)")
    parser.add_argument("--input", default="data/leads_sample.csv",
                        help="Path to input CSV (when --source=csv)")
    parser.add_argument("--output", default="output/enriched_leads.csv",
                        help="Path to output CSV (when --sink in {csv, both})")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N leads (useful for smoke tests)")
    parser.add_argument("--verbose", action="store_true", help="Debug-level logs")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    # Read
    if args.source == "csv":
        leads = read_csv_leads(args.input)
        log.info("Loaded %d leads from %s", len(leads), args.input)
    else:
        from . import io_sheets  # deferred import
        leads = io_sheets.read_leads()
        log.info("Loaded %d leads from Google Sheets", len(leads))

    if args.limit:
        leads = leads[: args.limit]
        log.info("Limiting to first %d leads", len(leads))

    # Enrich
    rows: List[EnrichedLeadRow] = []
    for lead in leads:
        try:
            rows.append(_enrich_one(lead))
        except Exception as e:
            log.exception("Failed to enrich lead %s (%s): %s", lead.name, lead.company, e)

    # Write
    if args.sink in ("csv", "both"):
        write_csv(rows, args.output)
        log.info("Wrote %d enriched rows to %s", len(rows), args.output)
    if args.sink in ("sheets", "both"):
        from . import io_sheets  # deferred import
        io_sheets.write_enriched(rows)

    _print_summary(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
