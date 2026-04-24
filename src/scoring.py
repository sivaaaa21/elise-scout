"""Lead scoring rubric for EliseAI inbound leads.

EliseAI sells AI leasing and resident-communication agents to multifamily
property managers, so a good lead is one where:

    1. The market is large (more units under management means more leasing
       volume, which means better ROI on automation).
    2. The market is rental-heavy (high % renters is a strong signal the
       company is multifamily-focused, which is our ICP).
    3. The market is premium (higher median rent correlates with operators
       that have budget for SaaS tooling).
    4. The company looks real and active (recent news or a Wikipedia page
       is a weak but useful signal the lead isn't a junk form-fill).

Each bucket is weighted; the total is 0-100. Thresholds below are starting
assumptions and should be tuned against closed-won data once we have it.

Tiers:
    HOT    >= 75     SDR calls same day
    WARM   50 - 74   personalized email sequence
    COOL   25 - 49   nurture track
    COLD    0 - 24   deprioritize
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional

from .apis.census import CensusSnapshot
from .apis.news import NewsSnapshot
from .apis.weather import WeatherSnapshot
from .apis.wikipedia import WikipediaSnapshot


# Weights (sum to 100)
W_MARKET_SIZE   = 40
W_RENTAL_MIX    = 30
W_RENT_LEVEL    = 15
W_COMPANY_SIGNAL = 15

# Thresholds
# Market size: ACS city population as a proxy for multifamily TAM.
POP_TIERS = [
    (1_000_000, 1.00),
    (  500_000, 0.85),
    (  250_000, 0.70),
    (  100_000, 0.50),
    (   50_000, 0.30),
    (        0, 0.10),
]

# Rental mix: share of occupied housing units that are renter-occupied.
RENT_MIX_TIERS = [
    (55.0, 1.00),
    (45.0, 0.80),
    (35.0, 0.55),
    (25.0, 0.30),
    ( 0.0, 0.10),
]

# Rent level: median gross rent in USD.
RENT_LEVEL_TIERS = [
    (2500, 1.00),
    (1800, 0.80),
    (1400, 0.60),
    (1000, 0.40),
    (   0, 0.20),
]


@dataclass
class LeadScore:
    total: int
    tier: str
    component_market_size: int
    component_rental_mix: int
    component_rent_level: int
    component_company_signal: int
    rationale: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _bucket(value: Optional[float], tiers) -> float:
    """Return the multiplier (0-1) for the first tier `value` clears."""
    if value is None:
        return 0.0
    for threshold, mult in tiers:
        if value >= threshold:
            return mult
    return 0.0


def _tier(total: int) -> str:
    if total >= 75:
        return "HOT"
    if total >= 50:
        return "WARM"
    if total >= 25:
        return "COOL"
    return "COLD"


def score(
    census: CensusSnapshot,
    news: NewsSnapshot,
    wiki: WikipediaSnapshot,
) -> LeadScore:
    rationale: List[str] = []

    # 1. Market size
    pop_mult = _bucket(census.total_population, POP_TIERS)
    c_market = round(W_MARKET_SIZE * pop_mult)
    if census.total_population:
        rationale.append(
            f"Market size: {census.city} has a population of "
            f"{census.total_population:,} → {c_market}/{W_MARKET_SIZE} pts"
        )
    else:
        rationale.append("Market size: unknown (no Census match) → 0 pts")

    # 2. Rental mix
    mix_mult = _bucket(census.renter_percentage, RENT_MIX_TIERS)
    c_mix = round(W_RENTAL_MIX * mix_mult)
    if census.renter_percentage is not None:
        rationale.append(
            f"Rental mix: {census.renter_percentage}% of occupied units are renter-"
            f"occupied → {c_mix}/{W_RENTAL_MIX} pts"
        )
    else:
        rationale.append("Rental mix: unknown → 0 pts")

    # 3. Rent level
    rent_mult = _bucket(census.median_gross_rent, RENT_LEVEL_TIERS)
    c_rent = round(W_RENT_LEVEL * rent_mult)
    if census.median_gross_rent:
        rationale.append(
            f"Rent level: median gross rent ${census.median_gross_rent:,} "
            f"→ {c_rent}/{W_RENT_LEVEL} pts"
        )
    else:
        rationale.append("Rent level: unknown → 0 pts")

    # 4. Company signal (Wikipedia + recent news)
    signal = 0.0
    if wiki.resolved:
        signal += 0.5
    if news.has_recent_news:
        # Scale: 1 article = +0.25, 3+ articles = +0.5
        signal += min(0.5, 0.25 + (news.total_results >= 3) * 0.25)
    signal = min(1.0, signal)
    c_signal = round(W_COMPANY_SIGNAL * signal)
    bits = []
    if wiki.resolved:
        bits.append("Wikipedia page found")
    if news.has_recent_news:
        bits.append(f"{news.total_results} recent news mentions")
    rationale.append(
        f"Company signal: {', '.join(bits) if bits else 'no public footprint'} "
        f"→ {c_signal}/{W_COMPANY_SIGNAL} pts"
    )

    total = c_market + c_mix + c_rent + c_signal
    return LeadScore(
        total=total,
        tier=_tier(total),
        component_market_size=c_market,
        component_rental_mix=c_mix,
        component_rent_level=c_rent,
        component_company_signal=c_signal,
        rationale=rationale,
    )


def _fit_narrative(census: CensusSnapshot, score_obj: LeadScore, city: str) -> Optional[str]:
    """One-line 'why this lead matters' summary for the SDR."""
    if not census.resolved or not census.total_population:
        return None
    pop = census.total_population
    renters = census.renter_percentage
    scale = (
        "top-tier metro" if pop >= 1_000_000
        else "major market"   if pop >= 250_000
        else "mid-sized market" if pop >= 50_000
        else "small market"
    )
    if renters is not None and renters >= 55:
        mix = f"{renters:.0f}% renter-occupancy — high lease velocity, strong multifamily demand"
    elif renters is not None and renters >= 40:
        mix = f"{renters:.0f}% renters — healthy multifamily market"
    elif renters is not None:
        mix = f"only {renters:.0f}% renters — owner-heavy market, lower fit"
    else:
        mix = "renter mix unknown"
    return f"Why this lead: {city} is a {scale} with {mix}."


def _recommended_action(tier: str) -> str:
    """Next step + SLA for the SDR, based on tier.

    The tier is already shown at the top of the brief, so we just return
    the concrete action here.
    """
    return {
        "HOT":  "Assign to enterprise AE, outreach within 24 hrs, book 30-min intro this week.",
        "WARM": "Personalized email this week, follow up in 3 business days.",
        "COOL": "Enroll in nurture sequence, revisit in 30 days.",
        "COLD": "Deprioritize for active outreach, keep on mailing list.",
    }.get(tier, "Review manually.")


def build_insights(
    person_name: str,
    company: str,
    city: str,
    state: str,
    census: CensusSnapshot,
    news: NewsSnapshot,
    wiki: WikipediaSnapshot,
    score_obj: LeadScore,
    weather: Optional[WeatherSnapshot] = None,
) -> List[str]:
    """SDR-facing brief, returned as markdown-ready lines.

    Each returned string is a bullet. Lines starting with two spaces are
    rendered as nested bullets in the UI. Dollar signs are escaped (\\$)
    because Streamlit otherwise renders $...$ as LaTeX math.
    """
    insights: List[str] = []

    # Fit assessment
    fit = _fit_narrative(census, score_obj, city)
    if fit:
        insights.append(f"**{fit.split(':', 1)[0]}:**{fit.split(':', 1)[1]}")

    # Conversation hooks the SDR can pivot off
    hooks: List[str] = []
    if census.resolved and census.median_gross_rent:
        hooks.append(
            f"Market rent: \\${census.median_gross_rent:,}/mo median in {city} — "
            f"reference in opener to show market expertise"
        )
    if wiki.resolved and wiki.description:
        hooks.append(
            f"Company context: {wiki.description.lower()} — use in opener to sound informed"
        )
    if news.has_recent_news and news.articles:
        art = news.articles[0]
        date = art.published_at.split("T")[0] if art.published_at else "recent"
        hooks.append(
            f"News angle ({date}): \"{art.title}\" — reference as the 'saw the news' opener"
        )
    if weather and weather.resolved and weather.description:
        temp = f"{weather.temperature_f:.0f}°F" if weather.temperature_f is not None else ""
        hooks.append(
            f"Local weather: {weather.description}{', ' + temp if temp else ''} in {city} — "
            f"soft opener for the email"
        )
    if hooks:
        insights.append("**Conversation hooks:**")
        insights.extend([f"  {h}" for h in hooks])

    # Risks / things to know
    risks: List[str] = []
    if score_obj.tier == "HOT":
        risks.append("Large operators often have incumbent leasing tools — prepare migration + integration talking points")
    if wiki.resolved and wiki.description and "trust" in wiki.description.lower():
        risks.append("Publicly-traded REIT — expect procurement rigor, lead with compliance/SOC2 content")
    if not news.has_recent_news and not wiki.resolved:
        risks.append("No public company footprint — qualify size and fit on the discovery call before investing outreach time")
    if census.resolved and (census.renter_percentage or 0) < 40:
        risks.append("Owner-heavy market — confirm their portfolio is actually rentals before pitching")
    if risks:
        insights.append("**Things to know:**")
        insights.extend([f"  {r}" for r in risks])

    # Recommended action
    insights.append(f"**Next step →** {_recommended_action(score_obj.tier)}")

    return insights
