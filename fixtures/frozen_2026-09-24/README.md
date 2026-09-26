# Frozen public-data input vintage

These three files are the input cache captured for the submitted 24 September 2026 screen. They are what `./run.sh replay` always uses, so it works from a fresh clone and so the isolated integration contract can rebuild the screen without network access.

- `manifest.json` records source, timestamps, adjustment policy and package versions.
- `universe.csv` records the exact constituent-security snapshot.
- `prices.csv.gz` contains the adjusted daily Yahoo bars used by the submitted run.

The cache is test/research evidence, not a live market-data service. It covers the price/volume core, not optional SEC responses. Yahoo may revise later downloads; use `./run.sh fresh` for a current screen.
