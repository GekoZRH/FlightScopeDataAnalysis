# Golf practice analysis

Analysis of FlightScope indoor practice sessions: a dashboard to review the latest session and follow progress, and printed carry-distance cards for the course.

## Run it

Use the `golf` conda environment (Python 3.13, numpy, pandas, scipy, matplotlib, plotly).

```
python -m golf dashboard     # opens the dashboard in your browser (Ctrl+C to stop)
python -m golf cards         # writes both printed cards without opening the dashboard
python -m pytest             # tests
```

## The dashboard

- **Data folders:** type or browse to the folder with the full swing CSV exports and the folder with the pitching CSV exports, then press Load data. Only the CSV files directly in a folder are read, so older exports can be kept in a subfolder.
- **Full swing / Pitching:** session review against the sessions before, progress per session, dispersion, and (pitching) accuracy by intent, straightness and which club for a distance.
- **Bag / Wedge intents:** choose which clubs and which wedge intents go on the cards.
- **Generate card:** each tab has a button that writes its printed card.

Cards are written to `Output/cards/<data folder>/` (for example `SwingData_Indoor`), once under a fixed name to print and once with the date of the last session in `archive/`. A different data folder gets its own card folder.

## Settings

- `golf.toml`: defaults for the bag, aliases for club names that were typed differently, the statistics thresholds (4 week window, 12 week fallback, minimum number of shots) and the look of the cards.
- `golf.local.json`: what you choose in the dashboard (data folders, bag, wedge intents). It overrides `golf.toml`, is not committed, and can be deleted to return to the defaults.

## Notes

- A `*` after a club on a card means there were too few shots in the last 12 weeks, so all shots on record were used.
- Ranges on the cards are the middle 68% and 95% of shots (the same shots as ±1 and ±2 standard deviations for a normal distribution). A skewed distribution is only used when there are at least 25 shots and it fits significantly better than a normal one.
- `Analysis_legacy/` is the original set of scripts, kept for comparison until the new code is trusted.
