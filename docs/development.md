# Development

## Setup and tests

```
conda activate golf            # Python 3.13; Python >= 3.11 is needed (tomllib)
python -m pytest               # about 210 tests, roughly a minute
```

`requirements.txt` lists the packages. The tests use made-up data in temporary folders and their own copy of the configuration, so they neither need your CSV files nor change your settings. A few extra checks run against your real data and are skipped when it is absent. The web server tests start a server on a free port.

## Code layout

```
golf/
  __main__.py, cli.py     python -m golf cards | dashboard
  config.py               golf.toml + golf.local.json  ->  Config
  ordering.py             standard order of clubs
  bag.py                  choose and order shots by bag, list available clubs
  sessions.py             list sessions, leave sessions out
  data/
    labels.py             "GW 50_9" -> club, variant, intent
    columns.py            raw CSV columns -> fixed names and units
    load.py               read the files into one table, one row per shot
    stack.py              stack sessions: the weight is read from the Club column
    garmin.py             Garmin export: nights, overnight vitals, activities
  stats/
    univariate.py         normal / skew-normal fit and ranges
    bivariate.py          joint lateral-carry model (Gaussian copula)
    intervals.py          t and chi-square intervals
    sessions.py           per-session statistics
    compare.py            exact and bootstrap comparisons of two samples
    summary.py            describe() and card_table()
    outcomes.py           one result number per session (stack speed, swing speed, carry spread), trend removal
    context.py            what Garmin recorded before each session (sleep, vitals, strength, cardio)
    correlation.py        Pearson r with Fisher z interval
  report/
    cards.py              draws a card (matplotlib)
    build.py              chooses the shots, draws and saves the card
  dashboard/
    service.py            all numbers the page shows, as plain data
    api.py                one function per URL, user errors become ApiError
    server.py             small local web server (standard library)
    static/               index.html, app.js, app.css (Plotly is served from the installed package)
tests/                    labels, columns, loading, statistics, cards, dashboard, stack, garmin, correlations
docs/                     this documentation
Analysis_legacy/          the original scripts
```

### How the data flows

```
CSV files  ->  load_shots()  ->  one table, one row per shot (golf/data)
           ->  include_sessions()    only the ticked sessions         (sessions.py)
           ->  select_bag()          only the ticked clubs / intents  (bag.py)
           ->  statistics            describe(), series(), review() ...  (stats/, dashboard/service.py)
           ->  JSON for the page, or a card as a PNG
```

`AppState` in `dashboard/service.py` holds the loaded tables and the settings. `state.in_bag(mode)` is every loaded session, `state.included(mode)` the ticked sessions, and `state.selected(mode)` the ticked sessions limited to the ticked clubs.

The table has columns such as `session_date`, `club`, `variant`, `intent` (12 = full swing), `label` (for example `gw 50_9`) and the measures with fixed names and units (`carry_m`, `lateral_m`, `club_speed_mph`, `spin_rpm` ...). Left is negative for all directional columns.

## The dashboard's interface

The page talks to the server with JSON. Requests carry the current choices; nothing but settings is stored on the server.

| URL | Method | Purpose |
|---|---|---|
| `/api/state` | GET | Folders, file and shot counts, notes about unselected clubs; `enabled` is false for a kind without a folder |
| `/api/load` | POST | Set the data folders (`swing_dir`, `pitching_dir`, `stack_dir`, `garmin_dir`) and reload. An empty value turns that kind off; a key that is left out keeps its folder |
| `/api/garmin/overview` | GET | Outcomes, clubs and predictors for the Garmin tab; says whether data and sessions suffice |
| `/api/garmin/table`, `/api/garmin/scatter` | GET | Correlation per Garmin measure; the points and fit of one of them (`outcome`, `club`, `detrend` 1 or 0, and `predictor` for the scatter) |
| `/api/stack/overview`, `/api/stack/progress` | GET | The selected stack sessions and weights; club head speed per session, one series per weight |
| `/api/browse` | POST | Show the folder dialog and return the folder |
| `/api/sessions` | GET, POST | List sessions with their selection; save the selection |
| `/api/bag` | GET, POST | Clubs found in the swing data; save the bag |
| `/api/wedges` | GET, POST | Wedge and intent grid; save the selection |
| `/api/swing/overview`, `/api/pitching/overview` | GET | Sessions, clubs and menus for the tab |
| `/api/swing/review`, `/api/pitching/review` | GET | Session review table (`session`, `baseline`) |
| `/api/swing/series`, `/api/pitching/series` | GET | One measure per session (`label`, `measure`) |
| `/api/swing/dispersion` | GET | Shots, rings and comparison (`label`, `session`, `compare`) |
| `/api/pitching/scatter` | GET | Two measures against each other (`club`, `x`, `y`) |
| `/api/pitching/straightness` | GET | Lateral miss per wedge and intent |
| `/api/pitching/ladder` | GET | Best wedge for a distance (`target`, `tolerance`) |
| `/api/card` | POST | Generate a card (`mode`) and return its URL |
| `/files/...` | GET | Generated cards (PNG files in the output folder only) |
| `/plotly.js`, `/`, `/app.js`, `/app.css` | GET | The page |

The functions behind these are in `dashboard/service.py` and can be called from Python or tests without a browser (see `tests/test_dashboard.py`).

### Safety

The server listens on `127.0.0.1` only. Because any web page you have open could send requests to a local port, a request is refused unless its `Host` header names the server, and every change (POST) must carry the header `X-Golf: 1`, which other sites cannot add. Only PNG files below the output folder are served. The folder dialog runs in a separate process.

## Extending

| To ... | Change |
|---|---|
| Show another measure in the progress charts | add a line to `SERIES` in `dashboard/service.py` |
| Offer another measure in the scatter plot | add a line to `SHOT_MEASURES` in the same file |
| Read another CSV column | add it to `FIELDS` in `data/columns.py` (with its unit) |
| Read a new kind of club name | `data/labels.py`, with a case in `tests/test_labels.py` |
| Change the look of a card | constants at the top of `report/cards.py`, titles and notes in `golf.toml` |
| Add a Garmin measure | add it to `PREDICTORS` and to `session_context()` in `stats/context.py`; the Garmin tab picks it up |
| Add a result to explain | add it to `OUTCOMES` in `dashboard/service.py` and write its per-session function in `stats/outcomes.py` |
| Change a threshold | `[stats]` in `golf.toml`, documented in `StatsSettings` in `config.py` |

Write a test with the change. The dashboard tests build a small synthetic data set in `tests/test_dashboard.py` and are a good starting point.

## Git

- Personal data never goes into git: `*.csv`, `SwingData/`, `PitchingData/`, `stackdata/`, `garmindata/`, `Plot/`, `Output/` and `golf.local.json` are ignored. If you really need a CSV in the repository (for example a small test file), add it with `git add -f`.
- `.gitattributes` keeps text files with the same line endings in the repository whatever the machine.
- Local branches only so far; nothing has been pushed.

## Known leftovers

These were left in on purpose or by oversight and are safe to clean up.

- **Unused library code.** `rolling_sessions`, `compare_groups`, `bootstrap_ci` (in `golf/stats/`) and `bag_labels` (in `golf/bag.py`) are tested but not used by the dashboard. The settings `n_bootstrap` and `min_shots_compare` only feed `compare_groups`.
- **Unused fields.** The review functions still return change estimates (`d_mean`, `d_sd`), a `verdict` and the tighter/broader counts. The page no longer shows them; only the dispersion labels use the same exact test.
- **`Analysis_legacy/`.** The original scripts. They still run from inside that folder (they read `../SwingData`), but they were written for an older matplotlib (the skew-normal contour plots use a function removed in matplotlib 3.10) and they use a different club selection, so their numbers differ for clubs whose data or names changed. For clubs whose shots did not change, the new Gaussian means and ranges matched the old ones to three decimals when the new code was checked. Delete the folder once you trust the new numbers.
