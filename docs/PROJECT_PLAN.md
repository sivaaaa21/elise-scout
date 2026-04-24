# Project Plan: Rolling Out Lead Enrichment in the Sales Org

## 1. Problem & north-star metric

EliseAI SDRs spend ~15–25 min of manual research per inbound lead (company
lookup, market sizing, first-touch personalization). With inbound volume
growing, that's the single largest drain on SDR capacity and the biggest
gate on speed-to-lead.

**North-star metric:** median **speed-to-first-touch** on inbound leads,
from the current ~4 hours down to **<30 minutes**, without reducing reply
rate. Secondary metrics below.

| KPI | Baseline | 90-day target |
|---|---|---|
| Median time from inbound to first personalized email | ~4h | <30m |
| SDR research time per lead | 18m | <3m (review only) |
| Reply rate on first touch | X% | ≥ X% (non-regression) |
| Meetings booked per SDR per week | Y | +20% |
| Lead-to-SQL conversion rate | Z% | +10-15% |

## 2. Scope of MVP (v0.1)

- **In scope:** inbound web-form leads where Name, Email, Company, City,
  State, and Property Address are present. English-language outreach
  only. US-based properties only (Census is US-scoped).
- **Out of scope for MVP:** non-US enrichment, voice outreach,
  multi-touch sequencing, CRM auto-write-back (manual copy-paste first).

## 3. Testing the MVP

Testing happens in **three overlapping layers** before the tool ever
touches a real prospect.

### 3a. Unit / offline tests (engineering)
- Each API client has a fallback path: no key returns an empty
  snapshot, API error returns an empty snapshot. Verified by unit
  tests that stub `requests`.
- Scoring rubric has golden-output tests: given a hand-crafted Census
  bundle, the score and tier are deterministic.
- CSV I/O round-trip test: no column loss, no encoding drift.

### 3b. Shadow test (week 1)
- Run the enricher on the **last 30 days** of closed inbound leads
  (closed-won and closed-lost).
- Check: does the score separate won from lost? Target: closed-won
  median score ≥ 20 pts above closed-lost median.
- Have two SDR managers blind-rate 20 enriched leads on email quality
  (1-5 scale). Target ≥ 4.0 average before going live.

### 3c. Pilot (weeks 2-3)
- Two volunteer SDRs use the tool on new inbound leads, but still send
  emails manually (tool suggests, human sends). Measure:
  - Time saved per lead (self-report plus calendar sampling)
  - Edits the SDRs make to the suggested email (proxy for quality)
  - Reply rate vs. the control group (other SDRs doing it the old way)
- **Go/no-go gate:** pilot SDRs report ≥ 50% time saved AND reply-rate
  non-regression at p < 0.1 over ~150 emails per arm.

### 3d. Guardrails (always on)
- Email draft includes a visible "Review before sending" banner.
- Score thresholds are tunable via config, not a hard-coded constant.
- Every enrichment run is logged with inputs, outputs, API latencies,
  and error rates. Alert on >5% API failure rate.
- Rate-limit budget: NewsAPI free tier is 100 req/day, so we cap at
  80/day by the batch size, with pagination disabled.

## 4. Rollout plan

Phased to de-risk. Each phase has an explicit go/no-go gate.

### Phase 0: Foundation (Week 0)
- Stand up GitHub repo, CI, and a service account for Google Sheets.
- Populate `.env` secrets in GitHub Actions and in a shared 1Password vault.
- Create the shared `Inbound Leads - Enriched` Google Sheet and share
  it with the SDR team (read-only) and SDR managers (edit).

### Phase 1: Shadow + Pilot (Weeks 1-3)
- Shadow backtest (Week 1).
- 2-SDR pilot (Weeks 2-3) as described above.
- Exit criteria: pilot metrics hit targets; ≤ 2 critical bugs open.

### Phase 2: Team rollout (Weeks 4-5)
- Enable for the full SDR team (all inbound).
- Daily 15-min office hours with the GTM engineer for the first week.
- Retro at end of Week 5: what's noisy, what's missing, what to kill.

### Phase 3: Org-wide + CRM write-back (Weeks 6-8)
- Push enrichment data into Salesforce/HubSpot as custom fields
  (`elise_lead_score`, `elise_tier`, `elise_insights`,
  `elise_draft_subject`, `elise_draft_body`).
- Expose score in the inbound routing rules so HOT leads route to AEs
  directly, skipping the SDR layer for qualified mid-market+ accounts.
- AE team gets read-only access to the enrichment data on their
  existing lead views.

### Phase 4: Iteration (ongoing, starting Week 9)
- Add more data sources as ROI justifies them:
  - Paid enrichment (Clearbit, Apollo) for decision-maker titles.
  - Property-specific data (number of units) via CoStar or web scraping.
  - Intent signals (G2, Bombora).
- Re-weight the scoring rubric quarterly using closed-won/lost data.

## 5. Stakeholders & RACI

| Role | Function | Responsibility |
|---|---|---|
| **GTM Engineer** (me) | Owns tool | R: build, instrument, iterate |
| **VP Sales / Head of SDRs** | Exec sponsor | A: owns sales outcomes, approves gates |
| **RevOps** | Sales systems | C: CRM schema, routing rules, reporting |
| **Sales Enablement** | Training | C: SDR training, email playbook integration |
| **SDR Managers** | Day-to-day users | C: pilot feedback, shadow QA |
| **Marketing Ops** | Inbound forms | I: ensures form fields stay in sync |
| **IT / Security** | Risk | C: reviews API keys, PII handling, service-account scopes |
| **Data / Analytics** | Metrics | R: dashboards for the KPIs above |
| **Legal / Compliance** | Risk | I: reviews AI-drafted email disclosures, CAN-SPAM compliance |

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AI-drafted email goes out with factual error (hallucinated news) | Medium | High | "Review before sending" gate + template fallback + subject-line whitelist during pilot |
| Census/News API rate limits exceeded on high-volume day | Low | Medium | Daily batch cap, retry with exponential backoff, paid-tier upgrade path identified |
| SDRs reject the tool as "extra work" | Medium | High | Opt-in pilot, vocal champion on the team, time-saved metric visible in weekly sales standup |
| Score biases against smaller-market accounts that are actually ICP | Medium | Medium | Quarterly re-weighting against closed-won data, manual override for SDRs |
| Service account credentials leak | Low | High | Key rotation schedule, least-privilege scopes (Sheets only, single sheet), audit logs |
| NewsAPI matches wrong "Company" (e.g., a person with same name) | Medium | Medium | Exact-phrase search + confidence threshold + SDR review step |

## 7. Timeline at a glance

```
Week 0 : Foundation    █
Week 1 : Shadow test   ██
Week 2 : Pilot         ████
Week 3 : Pilot + retro ████
Week 4 : Team rollout  ██████
Week 5 : Team + retro  ██████
Week 6 : CRM writeback ████████
Week 7 : CRM + routing ████████
Week 8 : Org-wide      ██████████
Week 9+ : Iterate      continuous
```

## 8. Success criteria (90-day review)

1. 100% of inbound leads auto-enriched within 10 minutes of form submit.
2. Median speed-to-first-touch < 30 minutes (from ~4h baseline).
3. SDR reply rate non-regressed; meetings-per-SDR up ≥ 20%.
4. Lead-score correlation with closed-won: Spearman ρ ≥ 0.35.
5. Tool uptime ≥ 99% over any 30-day rolling window.

If all five hit, the tool graduates from "GTM experiment" to "core sales
infrastructure" and moves under RevOps ownership for long-term support.
