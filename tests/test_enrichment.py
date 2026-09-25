"""Synthetic SEC responses; never used as empirical context."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import requests
from pandas.testing import assert_frame_equal

from src.enrichment import (
    ContextClient, SourceUnavailable, context_cutoff, current_scope,
    enrich_shortlist, filter_filings, sec_context, submission_rows,
)

CUTOFF = pd.Timestamp("2026-09-25T00:00:00Z")
NOW = pd.Timestamp("2026-09-25T18:00:00Z")


def filings():
    return pd.DataFrame([
        ["0000000001-26-000001", "8-K", "2026-09-24", "2026-09-24T23:59:59Z", "good.htm", "2.02", "Earnings"],
        ["0000000001-26-000002", "8-K", "2026-09-24", "2026-09-25T00:00:01Z", "late.htm", "", ""],
        ["0000000001-26-000003", "10-Q", "2026-09-25", "2026-09-24T23:59:59Z", "next-day.htm", "", ""],
        ["0000000001-26-000004", "4", "2026-09-24", "2026-09-24T20:00:00Z", "ownership.htm", "", ""],
        ["0000000001-26-000005", "8-K/A", "2026-09-24", "2026-09-24T23:00:00Z", "amended.htm", "", ""],
    ], columns=["accessionNumber", "form", "filingDate", "acceptanceDateTime", "primaryDocument", "items", "description"])


def screen_inputs():
    screen = pd.DataFrame([dict(decision_date="2026-09-24", ticker="AAA", impulse_start="2026-09-15",
                                pm_visible=True, lean_score=70., lean="continuation", reason="Price/volume only")])
    members = pd.DataFrame([dict(ticker="AAA", company_name="Example Company")])
    meta = dict(decision_date="2026-09-24", data_observed_at_utc=NOW.isoformat(),
                snapshot_label="latest Thursday-close screen; Friday outcome pending")
    return screen, members, meta


class EnrichmentTests(unittest.TestCase):
    def test_context_cutoff_and_historical_guard(self):
        self.assertEqual(context_cutoff("2026-09-24", NOW), CUTOFF)
        early = pd.Timestamp("2026-09-24T21:00:00Z")
        self.assertEqual(context_cutoff("2026-09-24", early), early)
        _, _, meta = screen_inputs()
        self.assertTrue(current_scope("2026-09-24", meta, NOW))
        self.assertFalse(current_scope("2026-09-17", meta, NOW))
        self.assertFalse(current_scope("2026-09-24", meta, pd.Timestamp("2026-09-25T21:00:00Z")))

    def test_sec_acceptance_cutoff_forms_and_publication(self):
        start = pd.Timestamp("2026-09-15T04:00:00Z")
        result = filter_filings(filings(), start, CUTOFF, 1)
        self.assertEqual([row["form"] for row in result], ["8-K", "8-K/A"])
        self.assertTrue(result[0]["url"].endswith("/000000000126000001/good.htm"))
        rows = filings().iloc[:1].copy()
        rows.loc[0, "acceptanceDateTime"] = "2026-09-24T19:00:00"
        with self.assertRaises(SourceUnavailable):
            filter_filings(rows, start, CUTOFF, 1)

    def test_sec_successful_no_matches_and_bad_identity(self):
        rows = filings().iloc[[3]]
        payload = {"cik": "1", "tickers": ["AAA"], "filings": {"recent": rows.to_dict(orient="list"), "files": []}}
        with patch.object(ContextClient, "get", return_value=payload):
            with tempfile.TemporaryDirectory() as folder:
                result = sec_context(ContextClient(folder), "AAA", 1, pd.Timestamp("2026-09-15T04:00Z"), CUTOFF)
                self.assertEqual(result["sec_status"], "none")
                self.assertEqual(result["sec_filing_count"], 0)
                with self.assertRaises(SourceUnavailable):
                    sec_context(ContextClient(folder), "WRONG", 1, pd.Timestamp("2026-09-15T04:00Z"), CUTOFF)
        with self.assertRaises(SourceUnavailable):
            submission_rows({"form": []})

    def test_offline_miss_and_http_denial_are_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("src.enrichment.requests.get") as get:
                with self.assertRaises(SourceUnavailable):
                    ContextClient(folder, offline=True).get("https://example.org")
                get.assert_not_called()
            response = requests.Response(); response.status_code = 403; response.url = "https://example.org"
            with patch("src.enrichment.requests.get", return_value=response) as get:
                with self.assertRaises(SourceUnavailable):
                    ContextClient(folder).get("https://example.org")
                self.assertEqual(get.call_count, 1)

    def test_sec_failure_isolated_and_core_screen_unchanged(self):
        screen, members, meta = screen_inputs(); original = screen.copy(deep=True)
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            with patch("src.enrichment.cik_mapping", return_value=({"AAA": (1, "fixture")}, [])), \
                 patch("src.enrichment.sec_context", side_effect=SourceUnavailable("fixture SEC outage")):
                enrich_shortlist(screen, members, meta, out, now=NOW, cache_root=out / "cache")
            context = pd.read_csv(out / "current_screen_context.csv")
            self.assertEqual(context.iloc[0].sec_status, "unavailable")
            self.assertTrue(pd.isna(context.iloc[0].sec_filing_count))
            assert_frame_equal(screen, original)

    def test_historical_and_empty_screens_make_no_source_calls(self):
        screen, members, meta = screen_inputs()
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            for historical in [True, False]:
                selected = screen if historical else screen.iloc[:0]
                meta["snapshot_label"] = "historical Thursday snapshot" if historical else "latest Thursday-close screen"
                with patch.object(ContextClient, "get") as get:
                    enrich_shortlist(selected, members, meta, out, now=NOW, cache_root=out / "cache")
                    get.assert_not_called()
                context = pd.read_csv(out / "current_screen_context.csv")
                if historical:
                    self.assertEqual(context.iloc[0].sec_status, "not_requested_historical")
                else:
                    self.assertTrue(context.empty)


if __name__ == "__main__":
    unittest.main()
