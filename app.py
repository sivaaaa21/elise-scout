"""Elise Scout: the morning inbound-lead dashboard for EliseAI SDRs.

Run locally:
    streamlit run app.py

Scout is a thin dashboard on top of the enricher. It doesn't reimplement
any business logic; it just presents the enriched output in a way an SDR
would actually use each morning.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.apis import census as census_api
from src.apis import news as news_api
from src.apis import weather as weather_api
from src.apis import wikipedia as wiki_api
from src.email_gen import generate as generate_email
from src.io_csv import EnrichedLeadRow, Lead, read_leads, write_enriched
from src.scoring import build_insights, score as score_lead
from datetime import datetime, timezone

load_dotenv()

# Page setup
st.set_page_config(
    page_title="Elise Scout",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed",
)

OUTPUT_CSV = "output/enriched_leads.csv"
INPUT_CSV = "data/leads_sample.csv"

TIER_STYLE = {
    "HOT":  ("#ef4444", "🔥"),
    "WARM": ("#f59e0b", "🟡"),
    "COOL": ("#3b82f6", "🔵"),
    "COLD": ("#6b7280", "⚫"),
}


# Styling. A bit of custom CSS so it doesn't look like default Streamlit.
st.markdown(
    """
    <style>
      .block-container { padding-top: 1.5rem; max-width: 1400px; }
      h1, h2, h3 { letter-spacing: -0.01em; }
      .scout-hero {
          background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
          color: #f8fafc;
          padding: 1.5rem 1.75rem;
          border-radius: 14px;
          margin-bottom: 1.25rem;
      }
      .scout-hero h1 { color: #f8fafc; margin: 0; font-size: 1.9rem; }
      .scout-hero .tag { color: #94a3b8; margin-top: 0.25rem; font-size: 0.95rem; }
      .tier-pill {
          display: inline-block;
          padding: 2px 10px;
          border-radius: 999px;
          color: white;
          font-weight: 600;
          font-size: 0.78rem;
          letter-spacing: 0.04em;
      }
      .muted { color: #94a3b8; font-size: 0.85rem; }
      .score-big { font-size: 3.2rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1; }
      .data-card-label {
          color: #94a3b8;
          font-size: 0.72rem;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          margin-bottom: 0.4rem;
      }
      .footer { color: #94a3b8; font-size: 0.78rem; margin-top: 1rem; }
      .score-row { display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 2px; }
      .score-row .label { opacity: 0.85; }
      .score-row .value { font-variant-numeric: tabular-nums; opacity: 0.7; }
      /* Tighten progress-bar spacing */
      .stProgress > div > div { height: 8px !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# Data loading + enrichment helpers
@st.cache_data(show_spinner=False)
def load_enriched(path: str, _mtime: float) -> pd.DataFrame:
    """Read the enriched CSV. `_mtime` busts the cache when the file changes."""
    if not Path(path).exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _mtime(path: str) -> float:
    return Path(path).stat().st_mtime if Path(path).exists() else 0.0


def _clean(val) -> str:
    """Normalize a CSV cell to a plain string, empty if the cell is missing.

    Pandas reads blank cells as float('nan'), which is truthy in Python,
    so `if val:` passes and markdown renders `[name](nan)`. That resolves
    as a relative URL and navigates back to the app itself. Always route
    CSV-derived values through this helper before rendering.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "") else s


def enrich_one_lead(lead: Lead) -> EnrichedLeadRow:
    """Run the same enrichment pipeline used by the CLI for a single lead."""
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
        name=lead.name, email=lead.email, company=lead.company,
        property_address=lead.property_address, city=lead.city,
        state=lead.state, country=lead.country,
        score=score_obj.total, tier=score_obj.tier,
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


def append_to_csv(row: EnrichedLeadRow, path: str) -> None:
    existing = pd.read_csv(path) if Path(path).exists() else pd.DataFrame()
    new_df = pd.DataFrame([row.as_dict()])
    combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["email", "company"], keep="last")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)


def run_full_enrichment() -> tuple[bool, str]:
    """Re-run the full CLI enricher. Returns (success, log_tail)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "src.enricher",
             "--input", INPUT_CSV, "--output", OUTPUT_CSV],
            capture_output=True, text=True, timeout=300,
        )
        log_tail = (proc.stdout or "")[-1500:] + "\n" + (proc.stderr or "")[-1500:]
        return proc.returncode == 0, log_tail
    except Exception as e:
        return False, str(e)


def tier_pill(tier: str) -> str:
    color, _ = TIER_STYLE.get(tier, ("#64748b", ""))
    return f'<span class="tier-pill" style="background:{color}">{tier}</span>'


# Header
st.markdown(
    """
    <div class="scout-hero">
      <h1>🏢 Elise Scout</h1>
      <div class="tag">Your morning inbound lead brief · Powered by US Census · NewsAPI · Wikipedia · OpenWeather</div>
    </div>
    """,
    unsafe_allow_html=True,
)

df = load_enriched(OUTPUT_CSV, _mtime(OUTPUT_CSV))

# Empty state
if df.empty:
    st.info("No enriched leads yet. Run the enricher once to seed the pipeline.")
    if st.button("▶ Run enrichment on sample leads", type="primary"):
        with st.spinner("Enriching 12 sample leads across 4 public APIs..."):
            ok, log = run_full_enrichment()
        if ok:
            st.success("Done.")
            st.rerun()
        else:
            st.error("Enrichment failed.")
            st.code(log)
    st.stop()


# Pipeline summary at the top of the page
tier_counts = df["tier"].value_counts().to_dict()
last_enriched_ts = df["enriched_at"].max() if "enriched_at" in df.columns else "—"

cols = st.columns([1.2, 1, 1, 1, 1, 2])
with cols[0]:
    st.metric("Total leads", len(df))
with cols[1]:
    st.metric("🔥 HOT", tier_counts.get("HOT", 0))
with cols[2]:
    st.metric("🟡 WARM", tier_counts.get("WARM", 0))
with cols[3]:
    st.metric("🔵 COOL", tier_counts.get("COOL", 0))
with cols[4]:
    st.metric("⚫ COLD", tier_counts.get("COLD", 0))
with cols[5]:
    st.markdown(
        f'<div style="padding-top:0.7rem; text-align:right;" class="muted">'
        f"Last enriched<br/><b>{last_enriched_ts}</b></div>",
        unsafe_allow_html=True,
    )

st.divider()


# Two-column layout: lead list on the left, detail panel on the right.
left, right = st.columns([1.1, 2], gap="large")

df_sorted = df.sort_values("score", ascending=False).reset_index(drop=True)

# Keep the selected lead in session state so clicks survive reruns.
if "selected_idx" not in st.session_state:
    st.session_state.selected_idx = 0
st.session_state.selected_idx = min(st.session_state.selected_idx, len(df_sorted) - 1)

with left:
    st.markdown("### Ranked pipeline")
    st.caption("Sorted by score. Click a lead to open the brief.")

    for i, row in df_sorted.iterrows():
        tier = row["tier"]
        _, emoji = TIER_STYLE.get(tier, ("#64748b", ""))
        is_active = i == st.session_state.selected_idx
        label = f"{emoji}  **{row['company']}**  ·  {row['city']}, {row['state']}  ·  Score {row['score']}"
        if st.button(
            label,
            key=f"lead_{i}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state.selected_idx = i
            st.rerun()


with right:
    sel = df_sorted.iloc[st.session_state.selected_idx]
    tier = sel["tier"]
    tier_color, _ = TIER_STYLE.get(tier, ("#64748b", ""))

    # Header for the selected lead
    hdr_l, hdr_r = st.columns([3, 1])
    with hdr_l:
        st.markdown(f"### {sel['company']}")
        st.markdown(
            f"**{sel['name']}** · {sel['email']}  \n"
            f"{sel['property_address']}, {sel['city']}, {sel['state']}"
        )
    with hdr_r:
        st.markdown(
            f'<div style="text-align:right">'
            f'<div class="score-big" style="color:{tier_color}">{int(sel["score"])}</div>'
            f'<div>{tier_pill(tier)}</div>'
            f'<div class="muted" style="margin-top:4px">out of 100</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Score breakdown: one progress bar per component.
    st.markdown("##### Why this score")

    components = [
        ("Market size",    int(sel["component_market_size"]),    40),
        ("Rental mix",     int(sel["component_rental_mix"]),     30),
        ("Rent level",     int(sel["component_rent_level"]),     15),
        ("Company signal", int(sel["component_company_signal"]), 15),
    ]
    for label, pts, mx in components:
        st.markdown(
            f'<div class="score-row"><span class="label">{label}</span>'
            f'<span class="value">{pts} / {mx} pts</span></div>',
            unsafe_allow_html=True,
        )
        st.progress(pts / mx if mx else 0.0)

    st.write("")  # spacer

    # Three data cards: Market, Company, Local.
    c1, c2, c3 = st.columns(3)

    def _fmt_int(v):
        return f"{int(v):,}" if pd.notna(v) else "—"

    def _fmt_pct(v):
        return f"{v}%" if pd.notna(v) else "—"

    with c1:
        with st.container(border=True):
            st.markdown('<div class="data-card-label">Market · US Census ACS</div>', unsafe_allow_html=True)
            st.markdown(f"**Population:** {_fmt_int(sel.get('market_population'))}")
            st.markdown(f"**Renter share:** {_fmt_pct(sel.get('market_renter_percentage'))}")
            st.markdown(f"**Median rent:** ${_fmt_int(sel.get('market_median_rent'))}")
            st.markdown(f"**Median HH income:** ${_fmt_int(sel.get('market_median_income'))}")

    with c2:
        with st.container(border=True):
            st.markdown('<div class="data-card-label">Company · Wikipedia + News</div>', unsafe_allow_html=True)
            # pandas reads empty cells as NaN (a float), which is truthy.
            # Route every CSV-derived string through _clean so we get a
            # real empty string when the field is missing.
            wiki_desc = _clean(sel.get("wikipedia_description"))
            wiki_url = _clean(sel.get("wikipedia_url"))
            if wiki_url:
                desc_suffix = f" — {wiki_desc}" if wiki_desc else ""
                st.markdown(f"**About:** [{sel['company']}]({wiki_url}){desc_suffix}")
            else:
                st.markdown(f"**About:** {sel['company']} *(no Wikipedia page found)*")

            news_txt = _clean(sel.get("top_news_title")) or "No recent news found"
            news_url = _clean(sel.get("top_news_url"))
            news_src = _clean(sel.get("top_news_source"))
            if news_url and news_txt != "No recent news found":
                src_suffix = f" · *{news_src}*" if news_src else ""
                st.markdown(f"**Latest news:** [{news_txt}]({news_url}){src_suffix}")
            else:
                st.markdown(f"**Latest news:** {news_txt}")

    with c3:
        with st.container(border=True):
            st.markdown('<div class="data-card-label">Local · OpenWeather</div>', unsafe_allow_html=True)
            wdesc = _clean(sel.get("weather_description")) or "—"
            wtemp = sel.get("weather_temp_f")
            wtemp_str = f"{wtemp:.0f}°F" if pd.notna(wtemp) else "—"
            st.markdown(f"**{sel['city']}**")
            st.markdown(f"{wdesc.capitalize()}")
            st.markdown(f"**{wtemp_str}**")

    # Insights
    if isinstance(sel.get("insights"), str) and sel["insights"].strip():
        with st.expander("Insight bullets (paste into CRM note)", expanded=False):
            # Lines starting with two spaces are nested sub-bullets under
            # the previous section header. Emit as a single markdown block
            # so Streamlit renders the hierarchy properly.
            md_lines = []
            for line in sel["insights"].split("\n"):
                if line.startswith("  "):
                    md_lines.append(f"    - {line.strip()}")
                else:
                    md_lines.append(f"- {line}")
            st.markdown("\n".join(md_lines))

    # Draft email
    st.markdown("##### Draft outreach email")
    _provider_labels = {"openai": "OpenAI", "anthropic": "Anthropic", "template": "template"}
    _provider_raw = sel.get("email_provider", "template")
    _provider_display = _provider_labels.get(_provider_raw, _provider_raw)
    st.caption(f"Generated by: **{_provider_display}** · Review before sending")

    subj = st.text_input("Subject", value=sel["email_subject"], key=f"subj_{st.session_state.selected_idx}")
    body = st.text_area(
        "Body", value=sel["email_body"], height=260,
        key=f"body_{st.session_state.selected_idx}",
    )

    btn_l, btn_m, btn_r = st.columns([1, 1, 3])
    with btn_l:
        st.download_button(
            "📥 Download .eml",
            data=f"Subject: {subj}\nTo: {sel['email']}\n\n{body}",
            file_name=f"outreach_{sel['company'].replace(' ', '_')}.eml",
            mime="message/rfc822",
            use_container_width=True,
        )
    with btn_m:
        if st.button("✓ Mark sent", use_container_width=True):
            st.toast(f"Marked '{sel['company']}' as sent.")

    st.markdown(
        '<div class="footer">Enriched via US Census ACS · NewsAPI · Wikipedia · OpenWeather</div>',
        unsafe_allow_html=True,
    )


# Bottom-of-page actions
st.divider()

act_l, act_r = st.columns(2)

with act_l:
    with st.expander("➕ Add a new lead (live enrichment)"):
        st.caption("Scout will enrich this lead in real-time and append it to the pipeline.")
        with st.form("add_lead_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                name    = st.text_input("Name", placeholder="Jane Doe")
                email   = st.text_input("Email", placeholder="jane@acmerealty.com")
                company = st.text_input("Company", placeholder="Acme Realty")
            with c2:
                addr    = st.text_input("Property address", placeholder="123 Main St")
                city    = st.text_input("City", placeholder="Austin")
                state   = st.text_input("State (2-letter)", max_chars=2, placeholder="TX")
            submitted = st.form_submit_button("Enrich lead", type="primary")
        if submitted:
            if not (name and company and city and state):
                st.error("Name, company, city, and state are required.")
            else:
                lead = Lead(
                    name=name, email=email, company=company,
                    property_address=addr, city=city, state=state.upper(), country="US",
                )
                with st.spinner(f"Enriching {company} in {city}, {state.upper()}..."):
                    row = enrich_one_lead(lead)
                    append_to_csv(row, OUTPUT_CSV)
                st.success(f"{company} enriched — scored **{row.score} ({row.tier})**.")
                load_enriched.clear()
                st.rerun()

with act_r:
    with st.expander("🔄 Re-run full enrichment"):
        st.caption(
            "Triggers the same pipeline that GitHub Actions runs every weekday at 9am ET. "
            "Uses the current contents of `data/leads_sample.csv`."
        )
        if st.button("Refresh all leads", type="primary"):
            with st.spinner("Re-enriching all leads..."):
                ok, log = run_full_enrichment()
            if ok:
                st.success("Pipeline refreshed.")
                load_enriched.clear()
                st.rerun()
            else:
                st.error("Enrichment failed.")
                st.code(log)
