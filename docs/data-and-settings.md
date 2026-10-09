# Data and settings

## The CSV files

The program reads the CSV exports of the FlightScope simulator. Files are expected in the Windows-1252 encoding, as exported, one file per practice session (several files on the same day count as one session).

Only these columns matter; everything else in the file is ignored.

| Needed | Columns |
|---|---|
| Always | `Time`, `Club` |
| Used when present | `Index`, `Player`, `Shot Type`, `Carry [m]`, `Roll [m]`, `Total [m]`, `Lateral [m]`, `Curve Dist [m]`, `Smash`, `Flight Time [sec]`, `Spin [rpm]`, `Spin Axis [deg]`, `Club Path [deg]`, `Ball Speed [mph]`, `V-Plane [deg]`, `H-Plane [deg]`, `Launch V [deg]`, `Launch H [deg]`, `Height [m]`, `FTT [deg]`, `Dynamic Loft [deg]`, `Spin Loft [deg]`, `Club Speed [mph]`, `Descent V [deg]`, `AOA [deg]`, `Low Point [cm]`, `FTP [deg]`, `Lateral Impact`, `Vertical Impact` |

How the files are read:

- **Time** looks like `2026-04-03; 11-09-12`. The date is the session; shots of the same date are one session.
- **Left and right.** Columns such as `Lateral [m]` hold text like `4.5 R` or `3.0 L`. Right becomes positive and left negative, for all of `Lateral`, `Curve Dist`, `Spin Axis`, `Club Path`, `H-Plane`, `Launch H`, `FTT` and `FTP`. A plain `0.0` stays 0.
- **Repeated columns.** Some exports contain a column twice (`Club Speed [mph]` and `Club Speed [mph].1`). They are merged and the first value is used.
- **Units.** `Lateral Impact` and `Vertical Impact` appear in mm in some exports and in cm in others; both are converted to mm. A column whose unit is not the expected one (for example `Roll [ft/s/ft]` next to `Roll [m]`) is ignored.
- **Missing values.** A shot without a carry or lateral value is kept, but is left out of every calculation that needs it.
- **One file with shots from all clubs.** Clubs are told apart by the `Club` column, see below.

## Stack files

Stack (overspeed) training is exported by the simulator as a CSV file with fewer columns:

`Index, Player, Time, V-Plane [deg], H-Plane [deg], Club Speed [mph], Club`

- **Club** holds the weight of the club, for example `235g`. Every swing of a set carries the weight of that set, so a change of weight starts a new set.
- Only swings of the sets are expected in the file. Warm-up swings should be removed before exporting.
- The training app saves one folder per session (with the CSV and a screenshot). Both layouts are read: CSV files directly in the stack folder, or one folder level below it.
- Time, left and right (`2.5 R`, `1.0 L`) and the repeated header rules are the same as for the other files. A swing without plane values is kept (its club speed is valid).

## Garmin export

Garmin lets you download all your data (Garmin account, *Data Management*, *Export your data*). They e-mail a zip file. Unzip it into a folder, for example `garmindata`, and choose that folder in the dashboard. The folder may be the unzipped root, its `DI_CONNECT` folder, or the folder that holds `DI-Connect-Wellness` and `DI-Connect-Fitness`. No login or internet connection is needed.

What is read (everything else, which is a lot, is ignored):

| Files | What is used |
|---|---|
| `DI-Connect-Wellness/*_sleepData.json` | Each night: start and end, time asleep, deep, light, REM and awake time, sleep score |
| `DI-Connect-Wellness/*_healthStatusData.json` | Overnight heart rate variability and heart rate |
| `DI-Connect-Fitness/*_summarizedActivities.json` | Activities: type, start, duration, average heart rate, training load, sets and repetitions. Strength training is `strength_training`; running, cycling, swimming, hiking, rowing, elliptical, stair climbing and indoor cardio count as cardio (the list `CARDIO_TYPES` is in `golf/data/garmin.py`; walking does not). Everything else (including golf) is ignored |

- Garmin stores times in UTC. They are converted with the time zone in `golf.toml` (`[garmin] timezone`, default `Europe/Zurich`), including the change between summer and winter time. The first swing of a session is taken from the `Time` column of your CSV files, which is local time.
- A night appears once even if several files hold it. A session without a recorded night has no sleep values; it is simply left out of the comparisons that need them.
- The export is large (it can hold years of data and be over 100 MB) but it is only read when you press Load data, and it never leaves your computer. `garmindata/` is ignored by git.

## How club names are read

The `Club` text is split into **club**, **variant** and **intent**.

| FlightScope text | club | variant | intent |
|---|---|---|---|
| `7 Iron 245` | 7i | 245 | full |
| `Driver Ping` | driver | ping | full |
| `5W TS2`, `4H Maverik` | 5w, 4h | ts2, maverik | full |
| `GW 50` | gw | 50 | full |
| `GW 50_9`, `LW 58_10`, `SW 54_11` | gw, lw, sw | 50, 58, 54 | 9, 10, 11 |
| `2 iron MP-20 HBM` | 2i | mp-20 hbm | full |

- The club comes first: a number with `iron`, `wood` or `hybrid` (or `i`, `w`, `h`), `driver`, or a wedge (`pw`, `aw`, `gw`, `sw`, `lw`, or the long names such as `Gap Wedge`).
- Everything after it is the **variant**: the specific club, such as the Mizuno model (`245`, `241`) or the loft of a wedge (`50`, `54`, `58`). The same club number with two variants (the 8-iron `241` and `245`) are two separate entries.
- A suffix `_9`, `_10` or `_11` at the end is the **intent**, the swing strength you chose in the simulator (9, 10, 11 o'clock). No suffix means a full swing, stored as 12.
- Shown labels look like `8i 245` and `gw 50_9`.

Names the program cannot read (for example `Putter`) are kept but reported with an orange note in the dashboard.

### Aliases

If a club was named differently in some sessions, add an alias in `golf.toml` instead of editing the files:

```toml
[aliases.variant]
maverick = "maverik"        # "4H Maverick" is read as "4h maverik"

[aliases.label]
"gap wedge" = "gw 50"       # the early sessions that only said "Gap Wedge"
"5 wood" = "5w ts2"
```

Keys are lowercase and written without the `_<intent>` suffix. `[aliases.label]` replaces the whole club text, `[aliases.variant]` only the variant.

## `golf.toml`: the defaults

The file is in the project folder and is committed to git. Relative paths are relative to it.

| Section | Setting | Meaning |
|---|---|---|
| `[paths]` | `swing_dir`, `pitching_dir`, `stack_dir`, `garmin_dir` | Data folders used until you choose others in the dashboard. An empty value (`""`) means: no data of that kind |
| `[garmin]` | `timezone` | Your local time zone, to turn Garmin's UTC times into local times (default `Europe/Zurich`) |
| | `output_dir` | Where cards are written (default `Output`) |
| `[stats]` | `window_weeks`, `fallback_weeks` | The two "Last N weeks" quick buttons on the Sessions tab (4 and 12) |
| | `min_shots` | Fewer shots than this for a club on a card get a `*` (12) |
| | `min_shots_skew` | A skewed distribution is only considered from this many shots (25) |
| | `skew_alpha` | Significance level of the skew test (0.05) |
| | `ci_level` | Level of the intervals in the charts (0.95) |
| | `min_shots_session` | Shots a session needs for a dispersion ring or a tighter/broader label (5) |
| | `seed` | Fixed random seed, so the dispersion rings are the same every time |
| | `n_bootstrap`, `min_shots_compare` | Only used by the bootstrap comparison in the statistics library, which the dashboard does not use at present |
| `[aliases.*]` | | See above |
| `[bag.swing]` | `clubs`, `intents` | The default bag, `intents = [12]` means full swings only |
| `[bag.pitching]` | `clubs`, `intents` | The default wedges and intents |
| `[cards.swing]`, `[cards.pitching]` | `title`, `notes`, `xtick_step`, `minor_step`, `show_roll` | Look of each printed card. `notes` are the free text blocks (the wind and height rules of thumb) |

## `golf.local.json`: your choices

The dashboard writes everything you choose to `golf.local.json`, next to `golf.toml`. It overrides the defaults, is created when needed, and is ignored by git because it holds your paths.

```json
{
  "swing_dir": "C:\\data\\SwingData\\Indoor",
  "pitching_dir": "C:\\data\\PitchingData\\Indoor",
  "stack_dir": "",
  "garmin_dir": "C:\\data\\garmindata",
  "sessions": {
    "swing": {
      "C:\\data\\SwingData\\Indoor": { "excluded": ["2026-03-14", "2026-03-15"] }
    }
  },
  "bag": {
    "swing": { "clubs": ["driver ping", "3w ts2", "7i 245"] },
    "pitching": { "pairs": [["gw 50", 12], ["gw 50", 11], ["lw 58", 9]] }
  }
}
```

- A folder set to `""` (as `stack_dir` above; `garmin_dir` works the same way) means you chose to have no data of that kind; the dashboard then does not use it. A kind that is not listed uses the default from `golf.toml`.
- `sessions` stores the sessions you left out, per data folder (for full swing, pitching and stack). Sessions you add later are not in the list, so they take part automatically.
- `bag.swing.clubs` is always put in the standard order (driver, woods, hybrids, irons, wedges).
- `bag.pitching.pairs` are (wedge, intent) combinations, with 12 meaning a full swing.
- You may edit the file by hand while the dashboard is closed. Deleting it brings back the defaults.

## Where results go

| Path | Contents |
|---|---|
| `Output/cards/<parent>_<folder>/` | The printed cards of a data folder, for example `SwingData_Indoor` |
| `Output/cards/<...>/archive/` | A copy of every card, named with the date of the last session in it |
| `Plot/` | Output of the legacy scripts only |
