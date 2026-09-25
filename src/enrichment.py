"""Optional shortlist-only SEC context; never used by the core signal."""
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import quote

import pandas as pd
import requests

from src.data import SOURCE, schedule
from src.report import markdown_table

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/"
FORMS = {"8-K", "10-Q", "10-K", "6-K", "20-F"}
CONTEXT_HOUR_ET = 20
USER_AGENT = "DeeterResearchPrototype/1.0 (public quantitative research; Python requests)"


class SourceUnavailable(ValueError):
    pass


class ContextClient:
    """Bounded requests, explicit cache vintage, and offline replay (including failures)."""
    def __init__(self, folder, offline=False):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.provenance = []
        self.last_request = 0.

    def get(self, url, params=None, json_response=True):
        params = params or {}
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        path = self.folder / (key + ".json")
        if self.offline:
            if not path.exists():
                raise SourceUnavailable(f"offline cache miss: {url}")
            record = json.loads(path.read_text())
        else:
            record = dict(url=url, params=params, fetched_at_utc=pd.Timestamp.now(tz="UTC").isoformat(),
                          http_status=None, error=None, payload=None)
            # SEC allows <=10 requests/second; this sequential client stays below four.
            pause = .25
            headers = {"User-Agent": os.environ.get("SEC_USER_AGENT", USER_AGENT)}
            for attempt in range(2):
                time.sleep(max(0., pause - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                try:
                    response = requests.get(url, params=params, headers=headers, timeout=25)
                    record["http_status"] = response.status_code
                    response.raise_for_status()
                    record["payload"] = response.json() if json_response else response.text
                    record["error"] = None
                    break
                except (requests.RequestException, ValueError) as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    # Never repeatedly hit an access denial or unrecognized/bad request.
                    if record["http_status"] in (400, 401, 403, 404):
                        break
                    if attempt == 0:
                        time.sleep(1.)
            path.write_text(json.dumps(record, ensure_ascii=False))
        self.provenance.append({k: record[k] for k in ["url", "params", "fetched_at_utc", "http_status", "error"]}
                          | {"cache_file": str(path), "offline_replay": self.offline})
        if record["error"]:
            raise SourceUnavailable(record["error"])
        return record["payload"]


def context_cutoff(decision, observed):
    """Thursday-night limit, never later than the saved Yahoo observation cutoff."""
    night = (pd.Timestamp(decision).normalize() + pd.Timedelta(hours=CONTEXT_HOUR_ET)).tz_localize("America/New_York")
    return min(night.tz_convert("UTC"), pd.Timestamp(observed).tz_convert("UTC"))


def current_scope(decision, meta, now):
    """No network or attached context for historical screens, even on cached replays."""
    date = pd.Timestamp(decision)
    cal = schedule(date - pd.Timedelta(days=14), now.tz_convert("America/New_York").date())
    completed = cal[cal.market_close <= now].index
    thursdays = completed[completed.weekday == 3]
    friday = date + pd.Timedelta(days=1)
    return (not thursdays.empty and date == thursdays.max()
            and friday not in completed
            and not meta["snapshot_label"].startswith("historical"))


def cik_mapping(client, tickers):
    """SEC mapping first; public constituent CIKs are an explicit fallback, not a new universe."""
    wanted = set(tickers)
    mapping, warnings = {}, []
    try:
        payload = client.get(SEC_TICKERS)
        for row in payload.values():
            ticker = row["ticker"].replace(".", "-")
            if ticker in wanted:
                mapping[ticker] = (int(row["cik_str"]), SEC_TICKERS)
    except (SourceUnavailable, KeyError, TypeError, AttributeError, ValueError) as exc:
        warnings.append(f"SEC ticker map unavailable: {exc}")
    if wanted - mapping.keys():
        try:
            html = client.get(SOURCE, json_response=False)
            table = next(t for t in pd.read_html(StringIO(html)) if {"Symbol", "CIK"}.issubset(t.columns))
            for _, row in table.iterrows():
                ticker = str(row.Symbol).replace(".", "-")
                if ticker in wanted and ticker not in mapping:
                    mapping[ticker] = (int(row.CIK), SOURCE)
        except (SourceUnavailable, ValueError, KeyError, StopIteration) as exc:
            warnings.append(f"Constituent CIK fallback unavailable: {exc}")
    return mapping, warnings


def submission_rows(payload):
    required = ["accessionNumber", "form", "filingDate", "acceptanceDateTime", "primaryDocument"]
    if not isinstance(payload, dict) or not all(isinstance(payload.get(k), list) for k in required):
        raise SourceUnavailable("SEC submissions schema missing required arrays")
    n = len(payload["form"])
    if any(len(payload[k]) != n for k in required):
        raise SourceUnavailable("SEC submissions arrays have inconsistent lengths")
    return pd.DataFrame({k: payload[k] for k in required} | {
        "items": payload.get("items", [""] * n), "description": payload.get("primaryDocDescription", [""] * n)})


def filter_filings(rows, start, cutoff, cik):
    """Use actual acceptance timestamps, not filing/report dates. Reject ambiguous naive times."""
    selected = rows[rows.form.str.replace("/A", "", regex=False).isin(FORMS)].copy()
    accepted = []
    for value in selected.acceptanceDateTime:
        ts = pd.Timestamp(value)
        if pd.isna(ts) or ts.tzinfo is None:
            raise SourceUnavailable("SEC filing has missing/ambiguous acceptance timezone")
        accepted.append(ts.tz_convert("UTC"))
    selected["accepted_at_utc"] = pd.to_datetime(accepted, utc=True)
    selected = selected[(selected.accepted_at_utc >= start) & (selected.accepted_at_utc <= cutoff)]
    # filingDate can reflect next-day dissemination for late submissions: do not treat those
    # as Thursday public merely because their acceptance timestamp was Thursday evening.
    filed = pd.to_datetime(selected.filingDate, errors="coerce")
    if filed.isna().any():
        raise SourceUnavailable("SEC filing date missing; public-availability check impossible")
    selected = selected[filed.dt.date <= cutoff.tz_convert("America/New_York").date()]
    selected = selected.sort_values(["accepted_at_utc", "accessionNumber"], ascending=False).drop_duplicates("accessionNumber")
    records = []
    for r in selected.itertuples():
        records.append(dict(form=r.form, accession=r.accessionNumber, accepted_at_utc=r.accepted_at_utc.isoformat(),
                            filing_date=r.filingDate, items=r.items, description=r.description,
                            url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{r.accessionNumber.replace('-', '')}/{quote(r.primaryDocument, safe='/')}"))
    return records


def sec_context(client, ticker, cik, start, cutoff):
    source = SEC_SUBMISSIONS + f"CIK{cik:010d}.json"
    p = client.get(source)
    if int(p["cik"]) != cik or ticker not in {t.replace(".", "-") for t in p.get("tickers", [])}:
        raise SourceUnavailable("CIK/ticker identity mismatch in SEC submissions")
    rows = submission_rows(p["filings"]["recent"])
    if rows.empty:
        raise SourceUnavailable("Empty SEC submissions history cannot establish absence of filings")
    for archive in p["filings"].get("files", []):
        # Fetch only archives overlapping the short event window if recent rows do not cover it.
        if rows.empty or pd.to_datetime(rows.filingDate).min().date() > start.date():
            if pd.Timestamp(archive["filingFrom"]).date() <= cutoff.date() and pd.Timestamp(archive["filingTo"]).date() >= start.date():
                name = archive["name"]
                if "/" in name or not name.startswith(f"CIK{cik:010d}-submissions-"):
                    raise SourceUnavailable("Unexpected SEC archive path")
                rows = pd.concat([rows, submission_rows(client.get(SEC_SUBMISSIONS + name))], ignore_index=True)
    records = filter_filings(rows, start, cutoff, cik)
    return dict(sec_status="ok" if records else "none", sec_error="", sec_source_url=source,
                sec_filing_count=len(records), sec_filing_flag=bool(records), sec_filings_json=json.dumps(records),
                sec_latest_form=records[0]["form"] if records else None,
                sec_latest_accepted_at_utc=records[0]["accepted_at_utc"] if records else None,
                sec_latest_url=records[0]["url"] if records else None)


CONTEXT_COLUMNS = ["decision_date", "ticker", "company_name", "context_cutoff_utc", "sec_window_start_utc",
    "cik", "cik_source", "sec_status", "sec_error", "sec_source_url", "sec_filing_count", "sec_filing_flag",
    "sec_latest_form", "sec_latest_accepted_at_utc", "sec_latest_url", "sec_filings_json"]


def enrich_shortlist(screen, members, meta, out, *, offline=False, now=None, cache_root=Path("cache/context")):
    """Separate context CSV: callers cannot accidentally feed added features into the core."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if len(screen) > 10 or (not screen.empty and not screen.pm_visible.eq(True).all()):
        raise ValueError("Context input must be the final PM-visible shortlist (at most 10 names)")
    decision = pd.Timestamp(meta["decision_date"])
    eligible = current_scope(decision, meta, now)
    cutoff = context_cutoff(decision, meta["data_observed_at_utc"])
    folder = cache_root / cutoff.strftime("%Y%m%dT%H%M%SZ")
    client = ContextClient(folder, offline=offline)
    rows, warnings = [], []
    mapping = {}
    if eligible and not screen.empty:
        mapping, warnings = cik_mapping(client, screen.ticker)
    names = members.set_index("ticker").company_name.to_dict()
    for r in screen.itertuples():
        start = pd.Timestamp(r.impulse_start).tz_localize("America/New_York").tz_convert("UTC")
        row = dict.fromkeys(CONTEXT_COLUMNS)
        row.update(decision_date=str(decision.date()), ticker=r.ticker, company_name=names[r.ticker],
                   context_cutoff_utc=cutoff.isoformat(), sec_window_start_utc=start.isoformat())
        if not eligible:
            row.update(sec_status="not_requested_historical", sec_error="Historical SEC context is outside scope")
        else:
            print(f"SEC context: {r.ticker} through {cutoff.isoformat()}", flush=True)
            try:
                if r.ticker not in mapping:
                    raise SourceUnavailable("CIK mapping unavailable; filing absence cannot be determined")
                cik, source = mapping[r.ticker]
                row.update(cik=cik, cik_source=source)
                row.update(sec_context(client, r.ticker, cik, start, cutoff))
            except (SourceUnavailable, KeyError, ValueError, TypeError, AttributeError) as exc:
                row.update(sec_status="unavailable", sec_error=str(exc))
        rows.append(row)
    context = pd.DataFrame(rows, columns=CONTEXT_COLUMNS)
    context.to_csv(out / "current_screen_context.csv", index=False)
    manifest = dict(decision_date=str(decision.date()), context_cutoff_utc=cutoff.isoformat(),
                    generated_at_utc=now.isoformat(), current_scope=eligible, offline_replay=offline,
                    warnings=warnings, requests=client.provenance,
                    sec_status_counts=context.sec_status.value_counts().to_dict())
    (out / "context_metadata.json").write_text(json.dumps(manifest, indent=2))
    text = (f"# Shortlist context: {decision.date()}\n\n"
            f"Context cutoff: **{cutoff.isoformat()}** (Thursday night, at most 20:00 America/New_York). "
            f"Fetched/replayed: {now.isoformat()}. This is a bounded reconstruction, not an archived Thursday data vintage.\n\n"
            "SEC is optional context only: it has no effect on qualification, ranks, leans or Yahoo reasons. "
            "Historical Thursday tables are not enriched. `none` means a successful SEC query with no matching target forms; "
            "`unavailable` does not mean no filings.\n\n"
            "SEC counts target forms (including amendments) accepted since impulse start and by the cutoff, "
            "also excluding next-day filing dates.\n\n")
    if not eligible:
        text += "**Historical screen: enrichment skipped; no source requests were made.**\n\n"
    if warnings:
        text += "Source warnings: " + " | ".join(warnings) + "\n\n"
    text += markdown_table(context[["ticker", "sec_status", "sec_filing_count", "sec_latest_form",
                                   "sec_latest_accepted_at_utc"]]) + "\n\n"
    for r in context.itertuples():
        text += f"- **{r.ticker}** — SEC: {r.sec_error or r.sec_status}."
        if r.sec_latest_url:
            text += f" [Latest matching filing]({r.sec_latest_url})."
        text += "\n"
    text += ("\nSource corrections and filing dissemination delays prevent an exact archived information-set claim. "
             "No historical SEC outcome evaluation was performed.\n")
    (out / "current_screen_context.md").write_text(text)
    return manifest
