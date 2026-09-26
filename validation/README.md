# Prospective validation

This folder is deliberately separate from the retrospective event study. It is for future Thursday lists that were saved before their Fridays occurred; no prospective result is claimed yet.

For each of the next ten completed Thursdays:

1. Run `./run.sh fresh` after the market close and before Friday opens.
2. Confirm `outputs/runs/YYYY-MM-DD/run_metadata.json` records a pending Friday and retain that dated folder unchanged until Friday completes.
3. Record the run in `prospective_log.csv`, including the decision hash and automation run URL or local commit.
4. After Friday closes, run `./run.sh update-friday YYYY-MM-DD`. This appends outcomes without recalculating the saved Thursday features.
5. Record data failures and sector concentration; do not change thresholds during the ten-week period.

After ten completed Fridays, report the same continuation/neutral/stall rates and Friday excess returns as the retrospective study. Compare higher- and lower-lean groups, and repeat the analysis without close location because that component mechanically reduces the distance to a breakout. Keep missing-data and holiday weeks in the log but outside completed-outcome denominators.
