# Golf practice analysis

Analysis of FlightScope indoor practice sessions and of stack (overspeed) training, in two parts, plus an optional look at how your sleep and training (from a Garmin watch) relate to your results:

- **A dashboard** to review the latest session, follow your progress over time, and see how your carry and your misses are distributed, for full swings and for wedge swings with different intents (9, 10, 11 o'clock), and the progress of your stack training per weight. The **Health** tab shows your Garmin sleep and recovery trends and your Withings weight and body composition, and relates your results to sleep, recovery and strength or cardio training before each session.
- **Printed cards** with the carry distance of each club and its distribution, to take to the course.

Everything runs on your own computer. The data never leaves it.

## Quick start

Use the `golf` conda environment (Python 3.13 with numpy, pandas, scipy, matplotlib and plotly; Python 3.11 or newer is required).

```
conda activate golf
python -m golf dashboard      # opens the dashboard in your browser; Ctrl+C stops it
python -m golf cards          # writes both printed cards without opening the dashboard
python -m pytest              # runs the tests
```

After a practice session:

1. Export the session from the simulator as CSV and save it in your data folder (for example `SwingData/Indoor`, `PitchingData/Indoor` or `stackdata`). You do not need all three kinds of data; a kind you do not have is simply left empty in the dashboard.
2. Start the dashboard and press **Load data**. The new session is selected automatically.
3. Review the session, then press **Generate card** on the Full swing or Pitching tab if you want a new printed card.

## Documentation

| Document | What it covers |
|---|---|
| [User guide](docs/user-guide.md) | Every tab and button, the printed cards, adding new clubs, troubleshooting |
| [Data and settings](docs/data-and-settings.md) | The CSV format, how club names are read, `golf.toml` and `golf.local.json` |
| [Statistics](docs/statistics.md) | How every number and range is calculated, and what it can and cannot tell you |
| [Development](docs/development.md) | Code layout, the dashboard's interface, tests, known leftovers |

## What is in this folder

| Path | Contents |
|---|---|
| `golf/` | The program |
| `tests/` | Automated tests (they use made-up data, so they run without your CSV files) |
| `docs/` | The documentation above |
| `golf.toml` | Default settings, committed |
| `golf.local.json` | Your own choices from the dashboard (folders, sessions, bag). Created automatically, not committed |
| `SwingData/`, `PitchingData/`, `stackdata/` | Your exported sessions (the folders can be anywhere; these are the defaults). Not committed |
| `garmindata/`, `withingsdata/` | Your Garmin and Withings data exports (optional). Not committed |
| `Output/` | Generated cards. Not committed |
| `Analysis_legacy/` | The original scripts, kept for comparison until the new code is trusted |

Personal data stays out of git: CSV files, the data folders, `Output/`, `Plot/` and `golf.local.json` are ignored (see `.gitignore`).
