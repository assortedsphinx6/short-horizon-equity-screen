"""Public constituent snapshot and explicitly adjusted Yahoo daily bars."""
from io import StringIO
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import requests
import yfinance as yf

SOURCE = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
OHLCV = ["open", "high", "low", "close", "volume"]


def schedule(start, end):
    return mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)


def universe(now):
    response = requests.get(SOURCE, headers={"User-Agent": "DeeterResearchPrototype/1.0"}, timeout=30)
    response.raise_for_status()
    table = next(t for t in pd.read_html(StringIO(response.text)) if "Symbol" in t)
    result = table[["Symbol", "Security", "GICS Sector"]].rename(
        columns={"Symbol": "original_symbol", "Security": "company_name", "GICS Sector": "sector"})
    result["ticker"] = result.original_symbol.str.replace(".", "-", regex=False)
    if len(result) < 450 or result.ticker.duplicated().any() or "SPY" in set(result.ticker):
        raise ValueError("Unexpected constituent table; refusing a partial or duplicate universe")
    result["source_url"] = SOURCE
    result["fetched_at_utc"] = now.isoformat()
    return result.sort_values("ticker").reset_index(drop=True)


def normalize(frame, ticker):
    if isinstance(frame.columns, pd.MultiIndex):
        level = next((i for i in range(frame.columns.nlevels)
                      if ticker in frame.columns.get_level_values(i)), None)
        if level is None:
            return pd.DataFrame()
        frame = frame.xs(ticker, axis=1, level=level)
    frame = frame.rename(columns=lambda x: str(x).lower().replace(" ", "_"))
    if not set(OHLCV).issubset(frame.columns):
        return pd.DataFrame()
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    frame.index.name = "date"
    if frame.index.duplicated().any():
        raise ValueError(f"Duplicate dates for {ticker}")
    for col in ("stock_splits", "dividends"):
        if col not in frame:
            raise ValueError(f"Missing corporate-action field {col} for {ticker}")
    frame = frame[OHLCV + ["stock_splits", "dividends"]].dropna(subset=OHLCV, how="all")
    return frame.sort_index()


def download(tickers, start, end):
    frames, failures = {}, {}
    for offset in range(0, len(tickers), 40):
        chunk = tickers[offset:offset + 40]
        print(f"Yahoo: {offset + 1}-{min(offset + 40, len(tickers))}/{len(tickers)}", flush=True)
        try:
            raw = yf.download(chunk, start=str(start.date()), end=str(end.date()),
                              auto_adjust=True, actions=True, repair=False, rounding=False,
                              keepna=True, prepost=False, group_by="ticker", threads=4,
                              progress=False, timeout=20)
        except Exception as exc:
            raw = pd.DataFrame()
            print(f"Chunk failed: {exc}", flush=True)
        for ticker in chunk:
            try:
                frame = normalize(raw, ticker)
                if frame.empty:
                    raise ValueError("empty OHLCV response")
                frames[ticker] = frame
            except Exception as exc:
                failures[ticker] = str(exc)
    for ticker in list(failures):
        for attempt in range(2):
            try:
                time.sleep(0.5)
                raw = yf.download([ticker], start=str(start.date()), end=str(end.date()),
                                  auto_adjust=True, actions=True, repair=False, rounding=False,
                                  keepna=True, prepost=False, threads=False, progress=False, timeout=20)
                frame = normalize(raw, ticker)
                if frame.empty:
                    raise ValueError("empty OHLCV response after retry")
                frames[ticker] = frame
                del failures[ticker]
                break
            except Exception as exc:
                failures[ticker] = str(exc)
    print(f"Downloaded {len(frames)} symbols; failures {len(failures)}: {list(failures.items())[:10]}", flush=True)
    return frames, failures


def save_cache(frames, members, metadata, folder):
    folder.mkdir(parents=True, exist_ok=True)
    members.to_csv(folder / "universe.csv", index=False)
    pd.concat([f.assign(ticker=t).reset_index() for t, f in frames.items()], ignore_index=True).to_csv(
        folder / "prices.csv.gz", index=False, compression="gzip")
    (folder / "manifest.json").write_text(json.dumps(metadata, indent=2))


def load_cache(folder):
    meta = json.loads((folder / "manifest.json").read_text())
    members = pd.read_csv(folder / "universe.csv")
    prices = pd.read_csv(folder / "prices.csv.gz", parse_dates=["date"], float_precision="round_trip")
    frames = {t: f.drop(columns="ticker").set_index("date") for t, f in prices.groupby("ticker")}
    return frames, members, meta


def invalid_bars(frame):
    a = frame[OHLCV].to_numpy(dtype=float)
    if not np.isfinite(a).all():
        return "missing_or_nonfinite_ohlcv"
    if (frame[["open", "high", "low", "close"]] <= 0).any().any() or (frame.volume < 0).any():
        return "nonpositive_price_or_negative_volume"
    if ((frame.high < frame[["open", "close", "low"]].max(axis=1)) |
            (frame.low > frame[["open", "close", "high"]].min(axis=1))).any():
        return "inconsistent_ohlc"
    return ""
