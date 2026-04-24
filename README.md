# Elise Scout: Inbound Lead Intelligence

> GTM Engineer practical assignment. A product an EliseAI SDR would
> actually use every morning. Turns raw inbound leads into a ranked,
> scored, outreach-ready briefing using free public APIs.

**Quick peek:**
- 📊 Streamlit dashboard: `streamlit run app.py`
- ⌨️ CLI + CSV: `python -m src.enricher`
- ⏰ Scheduled: GitHub Actions cron, weekdays 9am ET

## What it does

Takes a list of inbound leads (Name, Email, Company, Property Address,
City, State), enriches each one against four public data sources,
assigns a 0–100 lead score with a documented rubric, and writes a
personalized draft outreach email an SDR can review and send.

```
leads.csv / Google Sheet
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│                    enricher.py                          │
│                                                         │
│   ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌─────────┐   │
│   │ Census  │  │ NewsAPI  │  │  Wiki   │  │ Weather │   │
│   └────┬────┘  └─────┬────┘  └────┬────┘  └────┬────┘   │
│        └─────────────┴────────────┴────────────┘        │
│                       │                                 │
│              ┌────────▼─────────┐                       │
│              │ Lead Scoring     │                       │
│              │ Insights Builder │                       │
│              │ Email Generator  │                       │
│              └────────┬─────────┘                       │
└───────────────────────┼─────────────────────────────────┘
                        ▼
       enriched_leads.csv  /  Google Sheet (Enriched tab)
                        ▲
                        │
        ┌───────────────┴────────────────┐
        │    GitHub Actions (daily 9am)  │
        │    or manual CLI / UI trigger  │
        └────────────────────────────────┘
```

## Deliverables in this repo

- [`src/`](src/) - the enricher, scoring, and API clients.
- [`data/leads_sample.csv`](data/leads_sample.csv) - 12 realistic sample leads.
- [`.github/workflows/daily_enrich.yml`](.github/workflows/daily_enrich.yml) - scheduled + manual trigger.
- [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) - **Part B**: how to test and roll this out.
- [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) - every scoring assumption called out.
- [`docs/VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md) - cheat-sheet for the explainer video.

## APIs used (and why)

| API | Why it's here | Score contribution |
|---|---|---|
| **US Census ACS 5-Year** | Market sizing: population, renter %, median rent, median income for the property's city | 85% of the score |
| **NewsAPI** | Recent company news. Doubles as a legitimacy signal and as the strongest personalization hook for the email | 7.5% of the score + email hook |
| **Wikipedia (REST v1)** | Stable company context, used for the email opener and as a weak company-legitimacy signal | 7.5% of the score + email hook |
| **OpenWeather** | Pure icebreaker for the email opener ("hope you're staying dry in Houston…") | 0% of the score, email only |

All four are **free**. The tool runs with *any subset* of keys present;
missing keys degrade gracefully (the relevant snapshot just comes back empty).

## Quick start

```bash
# 1. Install
python -m venv .venv
# Windows PowerShell:
. .venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt

# 2. Configure: copy .env.example to .env and fill in whichever keys you have
cp .env.example .env
# (or in PowerShell:  Copy-Item .env.example .env )

# 3a. Run the CLI enricher against the sample CSV
python -m src.enricher --input data/leads_sample.csv --output output/enriched_leads.csv

# 3b. Or launch the Elise Scout dashboard
streamlit run app.py
# → open http://localhost:8501
```

### Running Elise Scout (the frontend)

Scout is a single-page dashboard that presents the enriched pipeline the way
an SDR would actually use it: a morning briefing, ranked leads, per-lead
detail with score breakdown, an editable draft email, and a live "Add new
lead" form that enriches one lead on the fly. It reads from the same
`output/enriched_leads.csv` the CLI produces, so the two workflows stay in sync.

```bash
streamlit run app.py
```

Three things you can do in the dashboard:
1. **Browse the morning pipeline.** See all leads ranked by score with tier
   breakdown (HOT / WARM / COOL / COLD).
2. **Open any lead's brief.** Score components, market stats, news,
   Wikipedia context, local weather, and an editable draft email you can
   download as `.eml`.
3. **Add a new lead live.** Paste in name / email / company / city / state
   and Scout enriches it in real time, appending it to the pipeline.

### Running against Google Sheets

```bash
# Prereqs:
#   - GCP service account JSON downloaded
#   - Sheet shared with the service-account email (as editor)
#   - GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_SHEETS_ID set in .env

python -m src.enricher --source sheets --sink sheets
```

The input tab needs columns: `name, email, company, property_address,
city, state` (and optional `country`). The output tab is recreated on
each run, so don't edit it in place. Layer SDR notes in a different tab
and `VLOOKUP` by email.

### Optional: richer email copy via LLM

Set `EMAIL_LLM_PROVIDER=openai` (or `anthropic`) and add the matching
API key in `.env`. The template generator is the fallback path, so if
the LLM call fails the batch never blocks.

## Output schema

Every row in `enriched_leads.csv` contains:

| Column | What it is |
|---|---|
| `name, email, company, property_address, city, state, country` | Inputs, echoed back |
| `score` | 0–100 |
| `tier` | HOT / WARM / COOL / COLD |
| `component_market_size, component_rental_mix, component_rent_level, component_company_signal` | Score breakdown |
| `market_population, market_renter_percentage, market_median_rent, market_median_income` | ACS signals |
| `wikipedia_description, wikipedia_url` | Wikipedia snapshot |
| `top_news_title, top_news_url, top_news_source, top_news_date` | Freshest news article |
| `weather_description, weather_temp_f` | Current weather at the property |
| `email_subject, email_body, email_provider` | The draft outreach email |
| `insights` | Newline-joined bullets the SDR can paste into the CRM |
| `enriched_at` | UTC timestamp of enrichment |

## Automation

**Scheduled:** `.github/workflows/daily_enrich.yml` runs at 14:00 UTC
(9am ET) on weekdays, reading from the `Leads` tab and writing to the
`Enriched` tab of the Sheet configured via `GOOGLE_SHEETS_ID`.

**Triggered:** the same workflow is exposed as a "Run workflow" button
in the GitHub Actions UI (`workflow_dispatch`), with an optional `limit`
input. SDRs can trigger ad-hoc runs without leaving their browser.

**Local:** `python -m src.enricher …` for dev and for the demo video.

## Design principles

- **Degrade gracefully.** A missing API key means an empty snapshot for
  that source, not a crash. The scoring rubric tolerates partial data.
- **Deterministic by default.** The template email generator produces
  byte-identical output for the same inputs, which is what you want for
  A/B testing subject lines.
- **Observable.** Every run prints a ranked summary and logs per-API
  latencies and failures. GitHub Actions uploads the output CSV as an
  artifact on every run.
- **Tunable.** All scoring weights and thresholds are constants in
  `src/scoring.py`. Re-weighting is a PR, not a deploy.

## Project structure

```
EliseAI/
├── README.md                    ← you are here
├── app.py                       ← Elise Scout Streamlit dashboard
├── requirements.txt
├── .env.example
├── .gitignore
├── data/
│   └── leads_sample.csv         ← 12 sample inbound leads
├── src/
│   ├── enricher.py              ← CLI entry point
│   ├── scoring.py               ← rubric + insight builder
│   ├── email_gen.py             ← template + optional LLM
│   ├── io_csv.py                ← CSV I/O
│   ├── io_sheets.py             ← Google Sheets I/O (optional)
│   └── apis/
│       ├── census.py
│       ├── news.py
│       ├── wikipedia.py
│       └── weather.py
├── .github/workflows/
│   └── daily_enrich.yml         ← cron + manual trigger
└── docs/
    ├── PROJECT_PLAN.md          ← Part B: test + rollout plan
    ├── ASSUMPTIONS.md           ← scoring logic + assumptions
    └── VIDEO_SCRIPT.md          ← demo video cheat-sheet
```

## What I'd build next (out of scope for this MVP)

1. **CRM write-back** to Salesforce/HubSpot custom fields, so scores
   drive routing rules (HOT leads skip SDR triage and go straight to AE).
2. **Portfolio enrichment:** number of units under management per
   company, via CoStar, Yardi, or a paid enrichment provider. This would
   likely dominate the score and is the single biggest missing signal.
3. **Re-weighting notebook** that ingests 60 days of closed-won/lost
   deals and suggests new scoring weights (sklearn logistic regression
   plus SHAP for interpretability).
4. **Multi-touch sequencer.** Today we produce one email; the natural
   extension is a 3-5 touch sequence with branching based on reply.
