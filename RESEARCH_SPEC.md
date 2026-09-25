# Frozen research specification

Authority: the original two-page Deeter Analytics assignment governs deliverables; this file records the frozen methodology. No older thresholds, fallback two-day window, liquidity filters, news scoring, optimization, or strategy backtest are used. SEC is optional context for the final current shortlist; the core below is unchanged and historical enrichment remains outside scope.

## Question and universe

Can a reproducible Thursday-close price/volume screen identify compressed setups following relative strength and elevated volume, provide an interpretable continuation/stall lean, and describe subsequent completed Friday behavior? Use a freshly retrieved current S&P 500 constituent snapshot, including multiple share classes, with Yahoo symbol normalization (`.` to `-`). SPY is only the benchmark and never ranked. Save source URL, fetch timestamp and exact membership. Projecting this snapshot backward introduces survivorship and selection bias.

## Exact windows and formulas

All offsets refer to the common ordered SPY trading-session index, ending on a completed Thursday `t`. Validate SPY against the NYSE schedule; missing SPY sessions invalidate the Thursday rather than shortening the trading windows. Features slice to `<=t` internally.

| Component | Definition | Numerical rationale |
| --- | --- | --- |
| Impulse | Five sessions `t-7..t-3`; stock return `C[t-3]/C[t-8]-1`, less the same SPY return | 5 is one trading week immediately preceding the pause. |
| Consolidation | Three sessions `t-2..t` | 3 makes “a few” executable without fitting a variable pause. |
| Baseline | Twenty sessions `t-27..t-8`, plus preceding close `t-28` | 20 approximates a trading month and excludes impulse contamination. |
| Volume | Mean impulse volume / median baseline volume | Mean captures participation throughout the impulse; median resists isolated historical spikes. |
| Current range | `(max(H[t-2..t])-min(L[t-2..t]))/C[t-3]` | Normalize a full three-session span by its immediately preceding close. |
| Normal range | Median of 18 analogous rolling three-session ranges ending `t-25..t-8` | 20 sessions contain exactly 18 complete three-session windows; first denominator is `C[t-28]`. |
| Compression | Current range / normal range | Compare equal-length windows within the same stock. |
| Qualification | Excess return **>0**, RVOL **>1**, compression **<1** | 0 is SPY parity; 1 is the stock's own normal participation/range. All are strict, unfitted boundaries. |
| Excitement | `100*(excess_return_percentile+rvol_percentile)/2` | Equal weights avoid unsupported importance estimates; 100 is display scaling. |
| Retention | `(C[t]-C[t-8])/(max(H[t-7..t-3])-C[t-8])`, clipped to `[0,1]` | 0/1 bound loss of the move and full retention; nonpositive denominator is unscorable. |
| Close location | `(C[t]-min(L[t-2..t]))/(max(H[t-2..t])-min(L[t-2..t]))` | Position within pause range; a zero-width tie gets the neutral midpoint 0.5. |
| Pause RS | `C[t]/C[t-3]-1` minus SPY over the same period | Isolate relative behavior during consolidation. |
| Lean | `100*(retention+close_location+pause_RS_percentile)/3` | Equal contribution from three interpretable components. |
| Lean boundary | `>50` continuation; `<50` stall; exactly `50` balanced | 50 is the midpoint, not a fitted economic cutoff. |
| PM display | Up to 10 qualifying, scorable names, excitement descending then ticker ascending | 10 limits reading burden; never fill with nonqualifiers. |
| Evidence horizon | Latest 12 calendar months through screen Thursday | About a year provides recent descriptive evidence within prototype scope. |
| Lean bins | `[0,20),[20,40),[40,60),[60,80),[80,100]` | Five equal-width descriptive intervals fixed before outcomes; include 100. |

Ranks use `pandas.rank(method="average", pct=True)` separately on each Thursday, over the **same valid stock population** for all three ranks, before qualification and retention exclusions. A tied group receives its mean ordinal rank divided by population size. Valid means complete finite required OHLCV and positive setup denominators. The close at `t-28` is required; this implementation conservatively validates its full OHLCV bar too. Save the entire rank population. Setup-qualified names with invalid retention remain in candidate audit and unconditional outcome statistics, but have no lean or PM display slot. A negative absolute impulse can still qualify if SPY did worse; flag and count it without adding an absolute-return filter.

The lean is partly cross-sectional (RS rank) and partly bounded raw measurements (retention/location). Neither score is a probability. Reasons report the actual component values and relative-strength direction; they cannot establish news attention, catalysts or institutional flow. Rounding is only for human-readable reports; decisions and CSVs retain computed precision.

## Data integrity and timing

Use Yahoo via `yfinance.download` with `auto_adjust=True`, `actions=True`, `repair=False`, daily regular-session bars and unrounded data. OHLC are adjusted consistently for corporate actions; volume is the raw field supplied by Yahoo, not multiplied by the OHLC adjustment factor. Yahoo may itself restate split history. Exclude any 29-session required window containing a reported split, and classify a split Friday as unavailable for outcome comparison. Dividend adjustments remain consistent across all OHLC. This does not guarantee detection of every vendor anomaly.

Reject missing/nonfinite bars, nonpositive prices, negative volumes, impossible high/low envelopes, duplicate dates, nonpositive median volume and zero normal range. Zero volume on individual days is permitted if the reference denominator stays positive. No forward filling. No silent partial-universe replacement. Download in 40-name chunks with four worker threads and two single-name retries for failures; these are transport controls, not research parameters. A 65-calendar-day warm-up buffer supplies more than 28 prior sessions; exact completeness is checked regardless. Record all failed downloads and per-Thursday exclusions.

The NYSE schedule supplies actual holidays and early closes. A bar is usable as completed only if its scheduled close is no later than the observation timestamp frozen **before** the download. Capturing that timestamp conservatively avoids a partial bar becoming “complete” because the download crossed the close. A cached replay retains the original timestamp, so replaying partial Friday data tomorrow cannot turn it into a completed outcome. Default execution fetches fresh data; `--replay` is explicit and offline. Daily data can still be delayed or revised after the exchange closes.

Default screen date is the latest completed Thursday available in SPY. If older than the expected completed Thursday, warn and label it historical. A completed following Friday also makes the screen a historical snapshot. An explicitly selected older date is historical. Before/during the latest Friday, label the outcome pending; never imply intraday refresh. `--as-of` must be a completed Thursday session with a SPY bar. Run and data timestamps use UTC and identify America/New_York market time.

## Outcome protocol

Generate and persist **all** Thursday decisions and full-universe ranks before the evaluator joins Friday bars; hash the saved decision file. Daily downloads contain both periods, but the feature API enforces a Thursday slice, and changing any Friday data must leave features, ranks, reasons and selected names unchanged.

Friday is exactly the next calendar day after Thursday. A Friday market holiday is skipped, without Monday substitution. A session not yet completed at the data observation cutoff is `pending` even if Yahoo supplies a daily bar. After completion, absent/invalid stock or SPY bars are `missing_data` rather than a stall. Both statuses are excluded from rates and return summaries.

For valid completed Fridays, evaluate in this order:

1. **Continuation:** Friday adjusted close strictly exceeds Thursday's consolidation high.
2. **Stall:** otherwise, Friday close is at or below Thursday close.
3. **Neutral:** otherwise.

Record strict intraday and closing breakout flags, stock close-to-close return, SPY return and their difference. Zero breakout buffer is the literal break of the range; zero return distinguishes unchanged/down closes from positive closes. The labels are operational, not proof of psychology or realized trading P&L.

Report scanned dates, holiday and missing dates, median valid universe, all qualifiers, unscorable qualifiers, negative absolute impulses, top-10 counts, available outcome counts, rates with denominators, mean/median stock and excess returns, fixed score buckets and higher/lower lean sanity checks. Clearly separate all-qualified from PM-visible populations. Sparse bins are underpowered; correlated same-Friday names are not independent observations.

## Alternatives, limitations and next test

“Excitement” could mean news or options attention; v1 observes price and volume. “Consolidation” could mean two sideways days or declining volume; v1 uses three-day range compression. “Goes again” could mean an intraday breakout or any positive close; v1 requires a closing breakout and retains other measurements separately. An absolute-gain condition is a possible future refinement, not a retrospective change.

Current constituents omit historical deletions and include additions before their membership dates. Today's adjusted history is not an archived Thursday vintage. Yahoo may be delayed, missing, revised or affected by actions. No free daily bars establish sentiment, order flow, borrow availability, executable prices, transaction costs, intraday path, portfolio positions or PM-specific catalysts. Fixed conventions are not empirically validated cutoffs; the same recent regime supplies only descriptive evidence, with no threshold search or out-of-sample claim. Obtain point-in-time constituents and archived corporate-action-consistent data, record prospective Thursday snapshots, and evaluate unchanged rules on held-out Fridays.

## Portfolio alert defaults and rationale

The separate half-page note is conceptual only. A signed, net-of-estimated-cost **1%** entry-notional gain avoids tiny quote noise; qualifying positions' **0.25% NAV** aggregate contribution requires materiality. **60 minutes since entry** defines an actionable “quickly.” At least **three distinct live positions** avoids two-out-of-two breadth, and **30% of all open positions** scales breadth to book size. Check every **five minutes** and require **two consecutive qualifying checks** to reduce transient triggers. Fire once, disarm; rearm only after **two consecutive nonqualifying checks AND 60 minutes since last alert**, then demand two fresh qualifying checks. There is no escalation exception. Missing/stale data suppress notification and reset consecutive counters without counting toward rearm. These are proposed defaults for PM discussion and internal replay, not learned from stock-screen results. Dollar gains versus percent/NAV gains, and acceleration in older positions versus gains since fresh entry, are distinct plausible requests.

Implementation references: [yfinance download parameters](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html), [exchange schedules](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html), [public membership table](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies).


## Current-shortlist context extension (follow-up request)

Run after the complete verified Yahoo pipeline; never change its decisions, score, reasons or historical tables. Only final PM-visible names receive SEC issuer requests. The separate context output is keyed by decision date/ticker; historical, stale or already-completed-Friday snapshots are skipped without network requests.

Use Thursday 20:00 America/New_York (a Thursday-night reading convention), capped at the saved data observation timestamp. SEC's window begins at impulse-start midnight Eastern. Count target forms 8-K/10-Q/10-K/6-K/20-F and their amendments using timezone-aware acceptance timestamps, bounded by this window. Require filing date no later than the cutoff's Eastern calendar date to avoid treating next-day dissemination as Thursday information. Save all matches plus latest form, timestamp and link. Mapping uses SEC first, with explicitly reported public-constituent CIK fallback and official submissions identity verification. A successful zero-match query is `none`; failure is `unavailable`, with null count/flag.

Bounded requests and raw-response caching permit SEC offline replay. HTTP 403 is not retried within a request. Source retrieval timestamps are separate from the Thursday information cutoff. These are reconstructed and potentially revised source histories, not archived contemporaneous data; no claims about causality, historical predictive value, or exact dissemination availability follow.
