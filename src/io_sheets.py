"""Google Sheets input/output adapter (optional).

Usage prerequisites:
    1. Create a GCP service account, download its JSON key.
    2. Share the target Sheet with the service account's email address.
    3. Set the following environment variables:
         GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
         GOOGLE_SHEETS_ID=<sheet id from the URL>
         GOOGLE_SHEETS_INPUT_TAB=Leads           (default)
         GOOGLE_SHEETS_OUTPUT_TAB=Enriched       (default)

The module imports gspread lazily so the rest of the tool works even
if the Google libraries aren't installed.
"""
from __future__ import annotations

import logging
import os
from typing import List

from .io_csv import EnrichedLeadRow, Lead, REQUIRED_COLUMNS

log = logging.getLogger(__name__)


def _open_sheet():
    import gspread  # type: ignore
    from google.oauth2.service_account import Credentials  # type: ignore

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    sheet_id = os.getenv("GOOGLE_SHEETS_ID")
    if not creds_path or not sheet_id:
        raise RuntimeError(
            "Google Sheets adapter needs GOOGLE_APPLICATION_CREDENTIALS and "
            "GOOGLE_SHEETS_ID environment variables set."
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id)


def read_leads() -> List[Lead]:
    sheet = _open_sheet()
    tab = os.getenv("GOOGLE_SHEETS_INPUT_TAB", "Leads")
    ws = sheet.worksheet(tab)
    records = ws.get_all_records()

    leads: List[Lead] = []
    for rec in records:
        normalized = {
            str(k).strip().lower().replace(" ", "_"): ("" if v is None else str(v).strip())
            for k, v in rec.items()
        }
        missing = [c for c in REQUIRED_COLUMNS if c not in normalized]
        if missing:
            raise ValueError(
                f"Sheet tab '{tab}' is missing columns: {missing}. "
                f"Found: {list(normalized.keys())}"
            )
        leads.append(Lead(
            name=normalized["name"],
            email=normalized["email"],
            company=normalized["company"],
            property_address=normalized["property_address"],
            city=normalized["city"],
            state=normalized["state"],
            country=normalized.get("country") or "US",
        ))
    return leads


def write_enriched(rows: List[EnrichedLeadRow]) -> None:
    sheet = _open_sheet()
    tab_name = os.getenv("GOOGLE_SHEETS_OUTPUT_TAB", "Enriched")

    try:
        ws = sheet.worksheet(tab_name)
        ws.clear()
    except Exception:
        ws = sheet.add_worksheet(title=tab_name, rows=1000, cols=40)

    if not rows:
        return

    dicts = [r.as_dict() for r in rows]
    header = list(dicts[0].keys())
    values = [header] + [[("" if v is None else v) for v in d.values()] for d in dicts]
    ws.update("A1", values, value_input_option="RAW")
    log.info("Wrote %d rows to tab '%s'", len(rows), tab_name)
