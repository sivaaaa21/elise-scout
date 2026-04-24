# Assumptions & Scoring Logic

This document captures every assumption baked into the enricher, so the
sales team can challenge and tune them against closed-won/lost data.

## About EliseAI's ICP

EliseAI sells AI leasing and resident-communication agents to multifamily
property managers, so a good inbound lead is one where:

1. **Market is large.** More units under management means more leasing
   volume, which means higher ROI from AI automation.
2. **Market is rental-heavy.** A high renter share signals the company
   is genuinely multifamily-focused (our ICP) rather than an HOA or
   single-family operator.
3. **Market is premium.** Higher median rent correlates with operators
   who can afford premium SaaS and have sophisticated leasing ops.
4. **Company is real and active.** A Wikipedia page or recent news
   coverage is a weak but useful signal that the lead is a legitimate
   operating entity, not a spam form-fill.

Important: we enrich on the lead's *property address city*, not the
company HQ city. That's deliberate. A Greystar HQ in SC tells us less
about that specific deal than the market where the property sits.

## Scoring rubric (0–100)

| Bucket | Weight | Signal |
|---|---|---|
| Market size | 40 | ACS city population |
| Rental mix | 30 | % of occupied units that are renter-occupied |
| Rent level | 15 | Median gross rent (USD) |
| Company signal | 15 | Wikipedia presence + recent news volume |

### Tier thresholds

| Tier | Score | Meaning | SDR action |
|---|---|---|---|
| **HOT** | ≥75 | High-confidence ICP match | Call within 4h + personalized email |
| **WARM** | 50–74 | Strong fit | Personalized email sequence (3 touches) |
| **COOL** | 25–49 | Partial fit | Add to nurture track |
| **COLD** | 0–24 | Weak fit or thin data | Deprioritize; revisit if data improves |

### Why these weights?

Weights are calibrated as starting points, **not** gospel:

- Market size is weighted highest because it's the most reliable
  predictor of revenue potential per account. An operator in Chicago
  simply has more units to automate than one in Burlington, VT.
- Rental mix is next. A city that's 60% renters is structurally
  multifamily-heavy (think NYC, DC). Low-renter markets skew to HOAs,
  condos, and SFR, which are further from our ICP.
- Rent level proxies for market sophistication and budget, but with
  diminishing returns, so it's capped at 15%.
- Company signal is the smallest bucket because it's the noisiest
  (NewsAPI false positives on common company names; Wikipedia coverage
  is uneven for private real-estate firms).

**Re-weighting cadence:** quarterly, based on observed lead→SQL→closed-
won correlations. The weights live in `src/scoring.py` as constants so
they're trivial to diff in a PR.

## Design principle: decline rather than hallucinate

Every optional enrichment source (Wikipedia, News, Weather) applies
**confidence filters** before its output enters the email or insights.
If the filter rejects the result, that field is left blank and the UI
shows "(no Wikipedia page found)" / "No recent news found" rather than
falling back to a best-guess match.

Rationale: an SDR's trust in this tool breaks on the second email that
references the wrong company. Empty context is recoverable; wrong
context is reputational damage. We'd rather show less than show
something misleading.

The confidence filters are documented per-API below.

## API-specific assumptions

### US Census (ACS 5-Year, most recent stable release)
- We match city name + state FIPS. If the city name is ambiguous
  (e.g. "Springfield"), we take the first prefix match, which could
  return the wrong Springfield. Log says "no Census match" if nothing
  matches.
- ACS is 5-year averaged data with a ~2-year publishing lag. Fine for
  structural market sizing, not fine for "just-opened-this-quarter"
  signals.
- "Place" geography excludes unincorporated suburbs. A property in
  "Paradise, NV" resolves, but "North Las Vegas" is a different place
  code. For ambiguous addresses, consider geocoding the street address
  first (out of scope for MVP).

### NewsAPI
- Free tier is **limited to articles up to 24 hours old** on the
  `/everything` endpoint in some plans. Watch for this in prod.
- Recency is sorted newest-first; we over-fetch ~10 articles per lead
  to give the validation filter room to work.
- **Two-signal validation filter** (added to prevent misleading email
  hooks): an article is kept only if BOTH hold:
  1. **Headline mentions the company.** NewsAPI can match on words in
     the article body while the headline is about something else
     (e.g. a Greystar press release titled "A New Take on Apartment
     Living Rises Above Murrieta at Montessa Heights", which is real
     but reads generic). SDRs paste the headline into outreach, so the
     headline must name the company.
  2. **Company appears 2+ times across title + description combined.**
     One mention could be incidental; two signals the article is
     materially about them.
- Generic single-token stems (e.g. "bell", "lincoln" after stripping
  suffixes) are refused. Too ambiguous to validate against without a
  second word for context.
- Net effect: we'd rather show "No recent news found" than inject a
  wrong hook into the email.

### Wikipedia
- **Three-layer confidence filter** to prevent misleading company
  context in the opener (e.g. "Lincoln Property Company" matching the
  Lincoln Motor Company, or "Pinebrook Management" matching a country
  singer). A page must pass all three:
  1. **Name match.** Company name (after stripping generic suffixes
     like "Company", "LLC", "Partners") must appear as a contiguous
     word-bounded phrase in the Wikipedia title. Multi-word companies
     require ≥2 tokens to remain after stripping, otherwise "Lincoln
     Property Company" matches on just "Lincoln".
  2. **Comma rejection.** Wikipedia uses commas for places
     ("Pinebrook, NY") and disambiguated people ("Bell, Anthony"),
     virtually never for companies. Any comma in the title, reject.
  3. **Domain keyword.** The page's description + extract must mention
     at least one real-estate term (*real estate, property, apartment,
     multifamily, rental, leasing, housing, residential, landlord,
     REIT, developer, condominium*, etc). This blocks cross-domain
     name collisions: same-named singers, racehorses, hospitals.
- Disambiguation pages are skipped.
- A missing Wikipedia page is expected for most mid-market property
  managers. It's a bonus signal, not a gate.

### OpenWeather
- Purely for email flavor; never affects the score. It exists because
  a "hope you're staying dry in Houston this week" opener beats a
  generic one, and it costs almost nothing.

## Sales insights

The `insights` column is not a restatement of the score breakdown (the
rubric is already surfaced in `component_*` columns and the UI progress
bars). It's written for the SDR's workflow, in four structured sections
per lead:

1. **Why this lead.** One plain-English sentence about fit, derived
   from market scale + renter share. *E.g. "NYC is a top-tier metro
   with 67% renter-occupancy; a property manager here is drowning in
   inbound inquiries."*
2. **Conversation hooks.** Specific, paste-ready angles drawn from the
   resolved data: market rent, company context (Wikipedia), most recent
   news, local weather. Each hook comes with a suggested use ("reference
   in opener", "soft opener for the email").
3. **Things to know.** Tier-driven risk flags:
   - HOT: expect incumbent tools, prepare migration talking points
   - Publicly-traded REIT (title or description says "trust"): expect
     procurement rigor, lead with compliance content
   - No public footprint: qualify size on discovery call
   - Owner-heavy market (<40% renters): confirm multifamily focus
4. **Next step.** Tier-driven SLA:
   - **HOT:** Assign to enterprise AE, outreach within 24 hrs
   - **WARM:** Personalized email this week, follow-up in 3 business days
   - **COOL:** Enroll in nurture sequence, revisit in 30 days
   - **COLD:** Deprioritize for active outreach, keep on mailing list

Dollar signs are escaped as `\$` because Streamlit renders `$...$`
as LaTeX math, which mangles numeric output.

## Email generation

- **Default: template.** Deterministic, reproducible, and easy to A/B
  test. Also zero variable cost.
- **Optional: LLM.** Gated behind `EMAIL_LLM_PROVIDER`. Falls back to
  the template on any failure, so the batch never blocks on a flaky
  model call.
- The template picks the strongest personalization hook available in
  this priority order: (1) recent company news, (2) Wikipedia
  description, (3) local weather, (4) generic opener.
- Subject lines also adapt: with news, "Quick thought after reading
  about X"; for hot/warm tier, "24/7 leasing for X in City"; otherwise
  generic.

## Open questions (to revisit)

1. Should we enrich **company HQ city** as well, to give SDRs a sense of
   which market the buyer sits in?
2. Should rent growth (5-year Δ) be its own signal? Stable-but-flat
   markets may still be great ICPs.
3. When we have CRM write-back, should scores live in SFDC and the CSV
   become debug-only?
