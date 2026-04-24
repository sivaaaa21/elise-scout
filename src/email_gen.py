"""Outreach email generator.

Two paths: a deterministic template (rule-based, always works) and an
optional LLM path (OpenAI or Anthropic) controlled by EMAIL_LLM_PROVIDER.
LLM failures fall back to the template.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from .apis.census import CensusSnapshot
from .apis.news import NewsSnapshot
from .apis.weather import WeatherSnapshot
from .apis.wikipedia import WikipediaSnapshot
from .scoring import LeadScore

log = logging.getLogger(__name__)


@dataclass
class DraftEmail:
    subject: str
    body: str
    provider: str  # "template", "openai", or "anthropic"


# ---------- Template generator ----------


def _first_name(full: str) -> str:
    return (full or "there").strip().split()[0]


def _humanize_pop(pop: Optional[int]) -> Optional[str]:
    """Format a population as '8.6M' or '44K' instead of a raw integer."""
    if not pop:
        return None
    if pop >= 1_000_000:
        return f"{pop / 1_000_000:.1f}M"
    if pop >= 1_000:
        return f"{pop // 1_000}K"
    return str(pop)


def _opener(
    first_name: str,
    company: str,
    city: str,
    state: str,
    census: CensusSnapshot,
    news: NewsSnapshot,
    wiki: WikipediaSnapshot,
    weather: WeatherSnapshot,
) -> str:
    """Pick the strongest personalization hook available."""
    # 1. Recent news headline
    if news.has_recent_news and news.headline_hook:
        return (
            f"Hi {first_name} — saw the piece on {company} "
            f"(\"{news.headline_hook}\") and it nudged me to reach out."
        )

    # 2. Renter-heavy market
    if census.resolved and census.renter_percentage and census.renter_percentage >= 50:
        return (
            f"Hi {first_name} — I've been watching the {city} rental market "
            f"({census.renter_percentage:.0f}% renter-occupied, some of the "
            f"hardest inbound volume in the country) and wanted to reach out."
        )

    # 3. Wikipedia company context
    if wiki.resolved:
        return (
            f"Hi {first_name} — have been following {company} for a bit "
            f"and wanted to reach out directly."
        )

    # 4. Weather as light filler
    if weather.resolved and weather.description:
        return (
            f"Hi {first_name} — hope the week in {city} is going well "
            f"({weather.description} out there today)."
        )

    return f"Hi {first_name} —"


def _why_line(census: CensusSnapshot, city: str, tier: str) -> Optional[str]:
    """Single sentence referencing Census figures. Tone scales with tier."""
    if not census.resolved:
        return None
    pop = _humanize_pop(census.total_population)
    rent = f"${census.median_gross_rent:,}" if census.median_gross_rent else None
    renters = (
        f"{census.renter_percentage:.0f}% renter-occupied"
        if census.renter_percentage is not None else None
    )
    bits = [b for b in (pop and f"{pop} residents", renters, rent and f"median rent {rent}") if b]
    if not bits:
        return None
    market_snippet = ", ".join(bits)
    if tier in ("HOT", "WARM"):
        tail = (
            "— operators there are fielding more after-hours inquiries than "
            "their leasing teams can realistically cover."
        )
    else:
        tail = (
            "— even smaller markets see steady after-hours inquiries that "
            "are worth catching before prospects move on to the next listing."
        )
    return (
        f"Quick reason I'm reaching out: {city} is a market we follow closely "
        f"({market_snippet}) {tail}"
    )


def _value_prop(score_obj: LeadScore, company: str) -> str:
    """Tier-specific pitch. References LeasingAI (SMS/email/chat) and VoiceAI (calls)."""
    if score_obj.tier == "HOT":
        return (
            "Our LeasingAI handles the full prospect flow 24/7 — SMS, email, "
            "chat, plus VoiceAI for inbound calls — so no inquiry sits in a "
            "queue and your on-site teams stay focused on in-person tours."
        )
    if score_obj.tier == "WARM":
        return (
            "Short version: LeasingAI is an agentic AI leasing agent that "
            "plugs into your stack, answers prospect inquiries around the "
            "clock, and books tours directly into your team's calendar."
        )
    # COOL / COLD
    return (
        "We help small and mid-sized operators plug coverage gaps outside "
        "business hours without hiring — LeasingAI replies instantly via "
        "SMS, email, and chat, then hands warm leads to your team the next "
        "morning."
    )


def _ask(first_name: str, company: str) -> str:
    """Call to action proposing a 15-minute intro."""
    return (
        f"Open to a 15-min intro next week? Happy to show how it'd plug into "
        f"the current leasing workflow at {company}."
    )


def _signoff() -> str:
    return "Regards,\nEliseAI"


def _subject(
    company: str,
    city: str,
    news: NewsSnapshot,
    score_obj: LeadScore,
) -> str:
    if news.has_recent_news and news.headline_hook:
        return f"Thoughts on the {company} news?"
    if score_obj.tier == "HOT":
        return f"24/7 leasing coverage for {company}?"
    if score_obj.tier == "WARM":
        return f"Quick idea for the {city} team at {company}"
    return f"Idea for {company}"


def _template_email(
    person_name: str,
    company: str,
    city: str,
    state: str,
    census: CensusSnapshot,
    news: NewsSnapshot,
    wiki: WikipediaSnapshot,
    weather: WeatherSnapshot,
    score_obj: LeadScore,
) -> DraftEmail:
    first_name = _first_name(person_name)

    paragraphs = [_opener(first_name, company, city, state, census, news, wiki, weather)]
    why = _why_line(census, city, score_obj.tier)
    if why:
        paragraphs.append(why)
    paragraphs.append(_value_prop(score_obj, company))
    paragraphs.append(_ask(first_name, company))
    paragraphs.append(_signoff())

    return DraftEmail(
        subject=_subject(company, city, news, score_obj),
        body="\n\n".join(paragraphs),
        provider="template",
    )


# ---------- Optional LLM generator ----------

LLM_SYSTEM_PROMPT = """You are writing a cold outreach email on behalf of the EliseAI sales team.

EliseAI builds an agentic AI leasing agent for multifamily property
managers. The flagship products are:
  * LeasingAI — handles prospect inquiries 24/7 across SMS, email, and chat
  * VoiceAI — answers and places phone calls with zero hold time
Together they schedule tours into the team's calendar and free human
leasing agents to focus on in-person tours and community events.
Reference the product names ("LeasingAI", "VoiceAI") naturally — never
the phrase "chatbot"; EliseAI is positioned as agentic AI.

Write a concise personalized outreach email (target: 90–120 words).

Hard requirements:
- Weather usage — STRICT:
  * When weather data is present, open with ONE short, natural-sounding
    sentence that reacts to the condition the way a human SDR would in
    a real email. Vary the phrasing — do not default to the rigid
    template "Hope the <X>°F and <condition> in <city> are treating
    you well." Instead, react to what the weather actually feels like:
      - cold / rain / snow → "Hope you're staying dry in <city> today."
                           → "Bit of a grey one in <city> — hope you're
                              keeping warm."
      - hot / sunny        → "Looks like a bright one in <city> today."
                           → "Hope you're finding shade out in <city>."
      - mild / pleasant    → "Nice-looking afternoon in <city> from what
                              I can see."
                           → "Hope the week in <city> is off to a good
                              start."
    Mentioning the temperature explicitly is optional — include it only
    when it sounds natural (e.g. "already 92°F in Houston — stay cool").
    Never dump both the number and the condition formulaically.
  * This line is an icebreaker ONLY. It must NEVER be tied to rental
    demand, renter behavior, leasing activity, tour traffic, or any
    other business rationale. Forbidden pattern: "with the sunny
    weather it's a great time for prospects to tour apartments."
  * The weather sentence does NOT count toward the two-data-point rule.
  * If weather data is missing, skip it and open with the hook below.
- Reference at least TWO concrete BUSINESS data points from the
  enrichment bundle. PREFER in this priority order: a news_articles
  headline, a Census stat (population, renter %, median rent), a
  Wikipedia fact about the company. Weave them in, never list them.
- Sound like a human SDR who did their homework, not a template. Short
  sentences. No corporate buzzwords ("synergy", "leverage",
  "revolutionize", "game-changer", "holistic", "turnkey").
- Match the lead_score.tier tone:
  * HOT: confident, assumes fit, specific value prop
  * WARM: curious, proposes exploration
  * COOL/COLD: humble, acknowledges smaller scale, low-friction ask
- Match number formatting: "8.6M" for millions, "44K" for tens-of-thousands,
  "$1,714" for currency. NEVER write "8622K residents".
- Structure:
  paragraph 1 = greeting on its own line: "Hi <FirstName>," (nothing else
    — keep it to this single salutation line).
  paragraph 2 = the weather icebreaker (if weather data exists) followed
    immediately by the personalized hook, as one flowing paragraph.
    Example shape: "Hope the 72°F and sun in Austin are treating you
    well. I came across Mile High Residential's recent expansion into
    the Denver metro…"
  paragraph 3 = why you're reaching out (use market/company context)
  paragraph 4 = what EliseAI does, tuned to the tier
  paragraph 5 = 15-min ask, natural and low-friction
  paragraph 6 = sign off as exactly "Regards,\nEliseAI" — the word
    "Regards," on its own line, then "EliseAI" on the next line. No
    first name, no team signature, no other variants ("Best", "Cheers",
    "Sincerely", etc. are all forbidden).
- Subject line: 4–8 words, specific to this lead. No exclamation points.
  Never include "[First Name]" or other template tokens.

Output strict JSON: {"subject": "...", "body": "..."} with "\\n\\n"
separating paragraphs in the body.
"""


def _llm_prompt_payload(
    person_name: str,
    company: str,
    city: str,
    state: str,
    census: CensusSnapshot,
    news: NewsSnapshot,
    wiki: WikipediaSnapshot,
    weather: WeatherSnapshot,
    score_obj: LeadScore,
) -> str:
    import json
    bundle = {
        "contact": {"name": person_name, "company": company},
        "property": {"city": city, "state": state},
        "census": census.as_dict() if census.resolved else None,
        "news_articles": [a.as_dict() for a in news.articles] if news.articles else [],
        "wikipedia": wiki.as_dict() if wiki.resolved else None,
        "weather": weather.as_dict() if weather.resolved else None,
        "lead_score": {"total": score_obj.total, "tier": score_obj.tier},
    }
    return json.dumps(bundle, indent=2, default=str)


def _openai_email(bundle_str: str) -> Optional[DraftEmail]:
    try:
        from openai import OpenAI
    except ImportError:
        log.warning("openai package not installed")
        return None
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None

    client = OpenAI(api_key=key)
    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user", "content": bundle_str},
            ],
            response_format={"type": "json_object"},
            temperature=0.6,
        )
    except Exception as e:  # pragma: no cover
        log.warning("OpenAI call failed: %s", e)
        return None

    import json
    try:
        payload = json.loads(resp.choices[0].message.content)
        return DraftEmail(subject=payload["subject"], body=payload["body"], provider="openai")
    except (KeyError, ValueError) as e:
        log.warning("OpenAI response malformed: %s", e)
        return None


def _anthropic_email(bundle_str: str) -> Optional[DraftEmail]:
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed")
        return None
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None

    client = anthropic.Anthropic(api_key=key)
    try:
        msg = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
            max_tokens=500,
            system=LLM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": bundle_str}],
        )
    except Exception as e:  # pragma: no cover
        log.warning("Anthropic call failed: %s", e)
        return None

    import json, re
    text = "".join(block.text for block in msg.content if hasattr(block, "text"))
    # Strip code fences if present
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        payload = json.loads(text)
        return DraftEmail(subject=payload["subject"], body=payload["body"], provider="anthropic")
    except (KeyError, ValueError) as e:
        log.warning("Anthropic response malformed: %s", e)
        return None


# ---------- Public entry point ----------

def generate(
    person_name: str,
    company: str,
    city: str,
    state: str,
    census: CensusSnapshot,
    news: NewsSnapshot,
    wiki: WikipediaSnapshot,
    weather: WeatherSnapshot,
    score_obj: LeadScore,
) -> DraftEmail:
    """Return a DraftEmail. Falls back to template if the LLM path fails."""
    provider = (os.getenv("EMAIL_LLM_PROVIDER") or "").strip().lower()
    if provider in ("openai", "anthropic"):
        bundle = _llm_prompt_payload(
            person_name, company, city, state,
            census, news, wiki, weather, score_obj,
        )
        llm_draft = (_openai_email if provider == "openai" else _anthropic_email)(bundle)
        if llm_draft:
            return llm_draft
        log.info("LLM email failed; falling back to template")

    return _template_email(
        person_name, company, city, state,
        census, news, wiki, weather, score_obj,
    )
