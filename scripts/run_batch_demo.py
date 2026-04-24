"""Run the enricher and print a summary. Same entrypoint the cron uses."""
from __future__ import annotations

import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "leads_sample.csv"
OUTPUT = ROOT / "output" / "enriched_leads.csv"


def main() -> int:
    leads_in = pd.read_csv(INPUT)
    print("Starting batch enrichment")
    print(f"  input : {INPUT.relative_to(ROOT)}  ({len(leads_in)} leads)")
    print(f"  output: {OUTPUT.relative_to(ROOT)}")
    print()
    print("Workflow for each lead:")
    print("  - Census ACS: market size + rent")
    print("  - Wikipedia: company context")
    print("  - NewsAPI: recent news")
    print("  - OpenWeather: current conditions")
    print("  - Score (0-100) + tier")
    print("  - Sales insights")
    print("  - Draft outreach email (OpenAI, with template fallback)")
    print()

    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "src.enricher",
         "--input", str(INPUT), "--output", str(OUTPUT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started

    if proc.returncode != 0:
        print("Batch failed. Last 20 lines of stderr:")
        print("\n".join(proc.stderr.splitlines()[-20:]))
        return proc.returncode

    df = pd.read_csv(OUTPUT)
    tier_counts = Counter(df["tier"])
    providers = Counter(df["email_provider"])

    print(f"Done in {elapsed:.1f}s ({elapsed / len(df):.1f}s/lead)")
    print(f"Processed {len(df)} leads. Email providers: {dict(providers)}")
    print()
    print("Tier distribution:")
    for tier in ("HOT", "WARM", "COOL", "COLD"):
        n = tier_counts.get(tier, 0)
        print(f"  {tier} - {n}")
    print()
    print("Top 5 by score:")
    cols = ["company", "city", "state", "score", "tier"]
    top = df.sort_values("score", ascending=False).head(5)[cols]
    print(top.to_string(index=False))
    print()
    print(f"Wrote: {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
