# Deeter Analytics: Thursday-close screen

A small, reproducible price/volume screen that turns the PM's "excitement, a few consolidation days, then Friday goes again or stalls" into fixed rules. It produces a Thursday-night list with a continuation/stall lean and a one-line reason for each name, a descriptive check of what happened on past Fridays, an eight-line PM note, and a half-page proposal for the portfolio alert.

The assignment is in [task.md](task.md). Exact formulas, data handling and the outcome protocol are in [RESEARCH_SPEC.md](RESEARCH_SPEC.md); this README is the operating guide.

## Quick start

Requires Python 3.11+ and `bash`. No credentials.

```sh
./run.sh setup     # create .venv and install requirements.txt (network: PyPI)
./run.sh test      # fast correctness suite, offline, about 15 seconds
./run.sh replay    # reproduce the submitted 24 September screen offline, about 2 minutes
```

Then, to screen the latest completed Thursday with current public data:

```sh
./run.sh fresh     # network: Wikipedia, Yahoo Finance, SEC EDGAR; about 2–3 minutes
```

**Dashboard:** open `outputs/dashboard.html` directly in any browser. It is one self-contained file (inline styles, data embedded, no scripts or network requests), so no server is needed. `./run.sh dashboard` is only an optional convenience that serves the same file at `http://127.0.0.1:8765/dashboard.html` (port set by `DASHBOARD_PORT`).

## Command reference

| Action | Command | Data / network | Writes to | Effect on saved results |
| --- | --- | --- | --- | --- |
| Install | `./run.sh setup` | PyPI | `.venv/` | None |
| Fast tests | `./run.sh test` | Offline; committed outputs and synthetic fixtures | Temporary folders only | None. The slow integration test is skipped here |
| Frozen end-to-end test | `./run.sh integration` | Offline; committed fixture | Temporary folder | None. Checks the 503 → 502 → 65 → 10 funnel, ticker order and decision hash |
| Reproduce the submission | `./run.sh replay` | Offline; always `fixtures/frozen_2026-09-24/` | `outputs/replay/` (ignored by Git) | None: root `outputs/` and the dated archive are untouched |
| Current screen | `./run.sh fresh` | Live Wikipedia constituents, Yahoo daily bars, SEC if the Friday is still pending | `outputs/`, `outputs/runs/<Thursday>/`, `cache/` | Replaces the root `outputs/` files; adds a dated archive, but never overwrites an existing one |
| Serve the dashboard (optional) | `./run.sh dashboard` | Local only | Nothing | None |

Advanced `main.py` options, run as `.venv/bin/python main.py …`:

- `--as-of YYYY-MM-DD` screens a specific completed Thursday with live data (non-Thursdays, holidays and unfinished sessions are rejected). Writes like `fresh`.
- `--render-only` rebuilds the PM notes and dashboard from the saved files in `--output-dir` (default `outputs/`) without any download.
- `--enrich-only` refreshes only the optional SEC context for the saved screen; it never changes a signal.

Tested on Python 3.11.4 (exact environment in `requirements-lock.txt`) and in a clean clone on Python 3.13.

## Replay versus fresh

**`./run.sh replay`** reproduces the submitted point-in-time snapshot.

- It always reads the committed input vintage in `fixtures/frozen_2026-09-24/`, whatever a previous `fresh` run left in `cache/`.
- It is deterministic: the screen, candidate audit and historical study are byte-identical to the committed outputs, with the same decision hash.
- It keeps the saved observation time (25 September 2026, 14:01 New York). Friday 25 September had not closed at that time, so that week's Friday outcome is `pending` (see below).
- The optional SEC response cache is not committed, so replay marks SEC context `unavailable` rather than inventing a "no filing" result.

**`./run.sh fresh`** runs the screen on today's public data.

- It fetches the current S&P 500 constituent list, downloads Yahoo daily bars, and screens the latest Thursday whose close has completed.
- It rewrites the root files in `outputs/` and rebuilds the 12-month event study with the same fixed rules.
- Numbers can differ slightly from the frozen snapshot even for the same Thursday, because Yahoo revises adjusted history.
- **Dated archive:** each run also saves `outputs/runs/<Thursday>/`. An existing dated folder is never overwritten. If a later run of the same Thursday produces different numbers, the frozen folder is kept, a `NOTE: existing archived decision … preserved` message is printed, `archive_status` is recorded in `outputs/run_metadata.json`, and the run still succeeds. This is why `outputs/runs/2026-09-24/` exists alongside the root files: the root files show the latest run, the dated folder keeps the submitted one.

Weekly use: run `fresh` after the Thursday close. Until Friday closes, that Friday stays `pending`. Any later run labels the completed Friday with the same rules. This is a repeatable research script, not a production service or a live Friday monitor.

## What the PM asked, and how it is operationalized

> Every week there are a few names everyone is excited about with volume, but then there are a few consolidation days. From there, either it goes again Friday, or it stalls. I want a list Thursday night…

```mermaid
flowchart LR
    A[Current S&P 500 securities<br/>plus SPY daily data] --> B[Validate a completed Thursday<br/>and 29-session windows]
    B --> C[Relative return,<br/>volume and compression]
    C --> D{Pass all 3<br/>strict rules?}
    D -- No --> E[Retained in audit only]
    D -- Yes --> F[Rank excitement<br/>and calculate lean]
    F --> G[Show up to 10 names<br/>with reasons]
    G --> H[After Friday closes:<br/>continuation / neutral / stall]
    G -. optional .-> I[Separate SEC context]
```

See the [detailed calculation, timing and exclusion flow](docs/methodology-flow.md) for every branch. All offsets are **trading sessions** ending at a completed Thursday close `t`, on the S&P 500 constituents, with SPY as the benchmark (SPY is never ranked).

| PM phrase | Executable rule | Number and why |
| --- | --- | --- |
| "excited about" | **Impulse**: stock return `C[t-3]/C[t-8]-1` minus SPY's return over the same sessions must be **> 0** | 5 sessions (`t-7..t-3`) = one trading week; 0 = SPY parity. Relative to SPY, so a stock can qualify on a down week if SPY fell more (flagged in outputs, not filtered) |
| "with volume" | **RVOL** = mean volume `t-7..t-3` ÷ median volume `t-27..t-8`, must be **> 1** | 20-session baseline ≈ one month, strictly before the impulse; 1 = the stock's own normal. Mean captures the whole impulse; median resists old spikes |
| "a few consolidation days" | **Compression** = 3-session range `t-2..t` ÷ median of 18 comparable 3-session ranges from the baseline, must be **< 1** | 3 sessions makes "a few" explicit; 1 = the stock's own normal range |
| "everyone" (ranking) | **Excitement** = 100 × mean(excess-return percentile, RVOL percentile), ranked across all eligible securities **before** filtering; show the top **10** qualifiers | Equal weights avoid unsupported importance claims; 10 bounds reading time |
| "leaning" | **Lean** = 100 × mean(retention, close location, pause-relative-strength percentile). **> 50** continuation, **< 50** stall, **= 50** balanced | Retention: share of the impulse still held. Close location: where Thursday closed in the 3-day range. Pause RS: return vs SPY during the pause. 50 is the midpoint, not a fitted cutoff |
| "goes again" | Friday close **>** Thursday's 3-session high | A literal closing break of the consolidation range |
| "stalls" | Friday close **≤** Thursday close; anything in between is **neutral** | Distinguishes a flat/down Friday from a positive close inside the range |

All three qualification inequalities are strict. The lean is a heuristic summary of Thursday's price action, **not a probability**.

**Where the words could mean two things.** "Excited about" could mean news, social or options attention; here it is proxied by unusual performance relative to SPY plus above-normal volume, which is a market-behavior proxy, not a measure of media attention. "Consolidation" could mean sideways days or declining volume; here it is three-session range compression. It does not require "no new high", so a failed new high still qualifies if the whole three-session range is tighter than the stock's normal range. "Goes again" could mean an intraday break or any up close; here it is a closing breakout, with the intraday break recorded separately.

**RVOL > 1 is deliberately permissive.** It is an above-baseline participation gate, not an extreme-volume threshold, and broad high-volume weeks make it weakly binding: for 24 September, 481 of 502 eligible constituent securities were above 1 (the impulse window included the 18 September quarterly expiration). The RVOL percentile inside the excitement score does the stronger discrimination for the displayed names.

## Friday outcomes and statuses

A Friday is labelled only after that Friday's session has fully closed, using completed daily bars:

- **continuation**: Friday close > Thursday's three-session consolidation high.
- **stall**: otherwise, Friday close ≤ Thursday close.
- **neutral**: every other completed case (a positive close still inside the range).

Each name's Friday also has a status (`status` in `friday_outcomes.csv`; `thursday_audit.csv` records the per-Thursday `friday_status`, which is one of the first three):

| Status | Meaning | In the evidence? |
| --- | --- | --- |
| `completed` | Friday closed before the run's observation time and valid stock and SPY bars exist | Yes; receives a label |
| `pending` | Friday had not closed at the run's observation time | No. Not a failed signal and not missing data |
| `holiday` | No Friday session; Monday is never substituted | No |
| `missing_data` | Friday closed, but a valid stock or SPY bar is absent, invalid or has a split | No |

The observation time is frozen before any download, and a bar only counts once its scheduled NYSE close has passed. The frozen replay therefore preserves the information state at the saved observation time: its Friday is `pending` and stays out of every completed-Friday rate. That is point-in-time integrity, not missing data. All historical rates use completed valid Fridays only.

## Reading the dashboard and screen

`outputs/dashboard.html` is generated from the saved CSV/JSON outputs every time the pipeline runs; it holds no numbers of its own.

1. **Funnel:** constituent securities loaded → eligible and ranked → passed all three rules → shown, plus pre-ranking exclusions.
2. **Data-quality status:** latest completed bar, failed downloads, exclusions, and the immediate Friday status with a sentence explaining it.
3. **Excitement:** the ranking score (0–100) that orders the list.
4. **Qualification numbers:** impulse vs SPY, RVOL and compression for each name.
5. **Lean and its inputs:** retention, close location and pause relative-strength percentile. Scores close to 50 carry little direction.
6. **Evidence and SEC context:** past-Friday rates for higher vs lower leans, and the optional filing check.

`outputs/current_thursday_screen.md` (readable) and `.csv` (full precision) contain the same rows:

| Column | Meaning |
| --- | --- |
| `stock_impulse_return`, `spy_impulse_return`, `excess_return` | Five-session impulse returns (fractions) and their difference; `excess_return > 0` is rule 1 |
| `rvol` | Impulse volume vs baseline (ratio); `> 1` is rule 2 |
| `compression_ratio` | Pause range vs normal range (ratio); `< 1` is rule 3 |
| `excess_return_percentile`, `rvol_percentile`, `excitement_score` | Cross-sectional ranks and their average (0–100); sets the display order |
| `retention`, `close_location`, `consolidation_rs_percentile` | The three lean inputs, each 0–1 |
| `lean_score`, `lean` | 0–100 score and its label; distance from 50 is the strength, so 49 or 51 is near neutral |
| `reason` | One line built from the numbers above |

## Submitted snapshot: Thursday 24 September 2026

This section describes the frozen, committed run. Data observed 25 September 2026, 14:01 America/New_York, while Friday was still trading, so its Friday outcomes are **pending**.

**503** S&P 500 constituent securities loaded (more than 500 because some issuers have several share classes) − **APH**, excluded because a stock split fell inside its required window = **502** eligible and ranked → **65** passed all three rules → **10** displayed. The other 55 qualifiers are in `outputs/current_thursday_candidates_audit.csv`.

| Ticker | Excitement | Lean score | Lean |
| --- | ---: | ---: | --- |
| WBD | 97.31 | 83.50 | continuation |
| SWKS | 96.02 | 41.74 | stall |
| CIEN | 93.73 | 49.26 | stall (near neutral) |
| QCOM | 93.23 | 64.37 | continuation |
| AMD | 89.64 | 94.79 | continuation |
| DXCM | 86.06 | 37.10 | stall |
| COIN | 85.96 | 49.94 | stall (near neutral) |
| FFIV | 85.56 | 55.20 | continuation |
| CRWD | 84.36 | 91.44 | continuation |
| INTC | 84.16 | 98.80 | continuation |

Seven of the ten are Information Technology, so the list is closer to one sector theme than ten independent ideas. The PM note is `outputs/pm_note_screen.md`.

## Evidence: what happened on Fridays

The same fixed rules were rerun on every Thursday from 25 September 2025 to 24 September 2026: 53 calendar Thursdays, 50 trading sessions, **46 with a completed Friday** (3 Friday holidays, 1 pending).

| Completed-Friday population | n | Continuation | Neutral | Stall | Mean return vs SPY |
| --- | ---: | ---: | ---: | ---: | ---: |
| All qualifiers | 2,448 | 16.7% | 35.2% | 48.1% | +0.03% |
| Displayed top 10 each week | 460 | 18.7% | 34.1% | 47.2% | −0.03% |

- Higher leans closed above the range far more often than lower leans (all qualifiers 25.3% vs 8.1%; top 10 25.6% vs 8.6%), but they **did not stall less** (all qualifiers 47.8% vs 48.4%; top 10 49.1% vs 44.4%) and there is **no demonstrated return edge**.
- Part of the breakout gap is mechanical: a Thursday close near the top of the range is already close to the breakout line.
- The 2,448 completed candidate events are clustered across only 46 completed Fridays, and names on the same Friday are correlated, so they should not be read as thousands of independent observations. No significance is claimed, and no costs, sizing or P&L are modelled.

Exact denominators, lean buckets and exclusions are in `outputs/historical_summary.md`.

**Traps, named.**

- *Look-ahead:* every feature and rank uses data up to Thursday only. A bar counts only after its scheduled NYSE close relative to a timestamp frozen before download. Friday data is joined in a separate step after the Thursday decisions are written. Tests mutate or delete all post-Thursday data and check that nothing changes.
- *Survivorship:* today's S&P 500 membership is projected backward, which drops deletions and includes additions before they joined.
- *Thresholds fitted to the answer:* the thresholds are fixed constants in `config.py`, applied unchanged to every Thursday, and the code performs no parameter search. The repository history cannot prove when they were chosen, so treat the evidence as descriptive, not as out-of-sample validation.

**What free data cannot test, and how to test it with the right data.** Daily Yahoo bars cannot show news or social attention, options activity, true order flow, the intraday path on Friday, or the data exactly as it looked on Thursday night. With point-in-time index membership, archived as-of-Thursday bars, timestamped news or social volume, options volume, and intraday Friday bars, the same rules could be re-tested without survivorship, with direct attention measures, and with a tradable Friday entry. The cheapest next step is prospective: save each Thursday's list before Friday and evaluate unchanged rules on those held-out Fridays. A comparison against non-qualifying stocks on the same Fridays would also be a natural extension.

## Optional SEC context

After the Yahoo screen is complete, the displayed names get a separate SEC EDGAR lookup: target forms (8-K, 10-Q, 10-K, 6-K, 20-F and amendments) accepted between impulse start and Thursday 20:00 New York time, capped at the data observation time. It answers "did a filing coincide with this move?" and **never** affects qualification, excitement, lean or Friday labels. If SEC fails, the screen still completes.

| `sec_status` | Meaning |
| --- | --- |
| `ok` | Query succeeded; target filings were found (count, latest form and link shown) |
| `none` | Query succeeded; no target filing in the window |
| `unavailable` | Query failed or no cached response; this does **not** mean "no filing" |
| `not_requested_historical` | Snapshot whose Friday had already closed, or a historical Thursday; no request is made |

For 24 September all ten names returned `none` in the live run; `replay` shows `unavailable` because SEC responses are not committed. For more reliable live SEC context, set `SEC_USER_AGENT="Name email@example.com"`; if SEC rejects or throttles the request, the context is marked `unavailable` and the core screen is unaffected.

**Not included:** direct news or social-media attention. It is future work, not a runtime dependency.

## Portfolio alert

`outputs/pm_note_portfolio_alert.md` is a half-page, no-code proposal for "doing well quickly on many positions". It defines doing well (at least 1% net gain per position, qualifying gains at least 0.25% of NAV), quickly (within 60 minutes of entry; the note explains the alternative "recent acceleration of the existing book" reading), many (at least 3 positions and at least 30% of open positions), a five-minute check cadence, and anti-noise rules (two consecutive confirmations, fire once, rearm only after two non-qualifying checks and 60 minutes). It is conceptual and untested; validating it needs internal positions and marks.

## Outputs

All in `outputs/` unless noted.

| File | What it is for |
| --- | --- |
| `dashboard.html` | Self-contained view of the run; open directly |
| `current_thursday_screen.{md,csv}` | The Thursday list: every rule input, lean and reason |
| `current_thursday_candidates_audit.csv` | Every qualifier for that Thursday, not just the ten shown |
| `pm_note_screen.md` | Eight-line PM note, generated from the saved outputs |
| `pm_note_portfolio_alert.md` | Half-page alert proposal |
| `historical_summary.md` | Readable Friday evidence with denominators and exclusions |
| `outcome_summary.csv`, `lean_buckets.csv`, `lean_sanity.csv` | The evidence tables behind the summary, note and dashboard |
| `historical_thursday_screens.csv`, `friday_outcomes.csv` | Every historical qualifier, and its Friday status and label, kept in separate files |
| `universe_features.csv` | The full ranked population on every Thursday (shows ranking happens before filtering) |
| `thursday_audit.csv`, `feature_exclusions.csv` | Per-Thursday status and every pre-ranking exclusion with its reason |
| `run_metadata.json`, `universe_snapshot.csv` | Data provenance, observation time, decision hash, archive status and the exact constituent list |
| `current_screen_context.{md,csv}`, `context_metadata.json` | Optional SEC context and request provenance |
| `runs/<Thursday>/` | Immutable dated snapshot; `runs/2026-09-24/` is the submitted run |
| `replay/` | Created by `./run.sh replay`; not committed |

A failed core run writes `outputs/RUN_FAILED.txt`; a failed SEC step writes `outputs/ENRICHMENT_FAILED.txt` and leaves the core results valid.

Code: `main.py` (command line), `src/pipeline.py` (steps in order), `data.py`, `features.py`, `screen.py`, `evaluate.py`, `report.py`, `dashboard.py`, `enrichment.py`; constants in `config.py`. Tests in `tests/` use synthetic fixtures, an independent numpy oracle for the frozen 24 September screen, and checks on the saved outputs.

## Limitations

- Current S&P 500 membership is projected backward (survivorship bias).
- Yahoo adjusted data is downloaded after the fact and revised over time; it is not an archived Thursday-night vintage.
- Windows containing a reported split are excluded, which cannot catch every vendor error.
- Historical events are clustered across 46 completed Fridays and correlated within each Friday.
- No news, social attention, options, order flow, intraday path, costs, borrow or portfolio data.
- The lean is a heuristic, not a calibrated probability; there is no demonstrated persistent edge.
- The 5/3/20 windows, top 10 and 50 midpoint are defensible conventions, not optimized or validated values.

AI use: I used AI-assisted tools to accelerate implementation, testing, and documentation; I selected the methodology and reviewed the resulting definitions and outputs.
