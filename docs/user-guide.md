# User guide

## Starting

```
conda activate golf
python -m golf dashboard
```

The dashboard opens in your browser at `http://127.0.0.1:8765/`. It only listens on your own computer. Stop it with Ctrl+C in the terminal.

- Port 8765 busy (for example another dashboard is still running)? Use `python -m golf dashboard --port 8766`.
- `--no-browser` starts it without opening a page.
- Close the terminal or press Ctrl+C when you are done; nothing runs in the background.

## The page

At the top are the three data folders (full swing, pitching and stack), then the tabs: **Sessions**, **Full swing**, **Pitching** and **Stack** on the left and **Bag** and **Wedge intents** on the right. The page opens on the first tab that has data, normally Full swing.

### Data folders

Type the folder with your full swing CSV exports, the folder with your pitching CSV exports and the folder with your stack CSV exports, or press **Browse** to pick them in the Windows folder dialog (it can open behind the browser window). Press **Load data** to read them. Below the buttons you see how many files, shots and sessions were found, and the last session.

**You do not need all three.** Leave a folder empty if you have no data of that kind: that kind is then not used, its tabs are not shown, and nothing else is affected. If all three are empty the page says so. Fill a folder in again and press Load data to bring the kind back.

- For full swing and pitching only the CSV files directly in the folder are read. To keep old exports out of the analysis, move them into a subfolder (for example `legacy data`).
- For stack data, the CSV files directly in the folder and in the folders one level below it are read, because the training app saves one folder per session. To keep a stack session out, untick it on the Sessions tab.
- Using a different folder is the way to keep data sets apart (for example indoor and outdoor). Each folder remembers its own session selection, and its cards are saved separately.
- An orange note appears when clubs were found in your data that are not selected yet, or when a club name could not be read. See "Adding a new club" below.

### Sessions tab

A session is one practice day. This tab lists every session of the loaded folders (full swing, pitching and stack, each in its own list) with its shot count, number of clubs (or weights) and the file it came from. **Tick the sessions that should take part.** Everything else in the dashboard uses only the ticked sessions: the reviews, the progress charts, the dispersion plot, the pitching plots and both printed cards.

- Quick buttons: **All**, **Last 4 weeks**, **Last 12 weeks** (counted back from the newest session in the folder), and **Last N sessions**.
- Changes apply at once and are remembered for that folder. Sessions you add to the folder later are ticked automatically.
- At least one session must stay ticked.

### Full swing tab

**Session review.** Choose a session and what to compare it with. One row per club with the session's mean carry, carry spread (standard deviation), and lateral spread next to the same numbers for the historic shots of that club.

"Compare with" decides what "historic" means:

| Choice | Historic shots |
|---|---|
| the 4 sessions before | the 4 sessions just before this one, from every loaded session, ticked or not |
| all earlier sessions | every earlier loaded session, ticked or not |
| all other selected sessions | the other ticked sessions, earlier or later (this session is left out) |

The small `n=` shows how many historic shots there are. Only the clubs ticked on the Bag tab are shown, and only their full swings.

**Progress.** For one club, three charts with the date of each selected session on the x-axis:

1. Mean carry per session.
2. Mean club head speed per session.
3. Any other measure, chosen in the menu: carry spread, lateral spread and lateral mean, ball flight (ball speed, smash factor, spin, launch angle, descent angle, peak height, flight time, spin axis) and club (club head speed spread, angle of attack, club path, dynamic loft, spin loft).

The shaded band is the 95% interval of each point (see [Statistics](statistics.md)). A session in which you did not hit the club has no point; the line continues across it. Wide bands mean few shots.

**Dispersion against earlier sessions.** Choose a club, a session and what to compare with. The plot shows where the shots of that session landed (lateral against carry) over the earlier shots, with the area holding the middle 68% of shots (solid) and 95% (dotted for this session, dashed for the earlier shots). Faint rings are the earlier sessions one by one. The table gives the carry and lateral spread now and before, and the labels "tighter", "similar" or "broader" say whether the difference is larger than normal shot-to-shot variation. "Similar" is the usual answer with a few shots; it does not prove nothing changed.

**Printed card.** See "Printed cards".

### Pitching tab

For wedge swings with intents (full, 11, 10, 9 o'clock).

- **Session review.** One row per wedge and intent: session and historic club head speed and its spread, session carry (simulated) and carry spread, session and historic lateral spread. Indoor carry is only simulated, so club head speed is the main measure here.
- **Progress.** Like the full swing tab, but you choose the wedge and the intent.
- **Compare two measures.** Choose a wedge, then any measure for the x-axis and the y-axis. Every shot of the ticked intents in the ticked sessions is plotted, one colour per intent (full blue, 11 green, 10 amber, 9 pink). "Fit line" adds one straight line through all plotted shots and the note under the plot gives the correlation. The line pools all intents, so it mostly shows that harder swings go further.
- **Which is straighter to the target?** The lateral miss of every selected wedge and intent: the dot is the average miss (negative is left of the target line), the thin bar the middle 68% of shots and the wide bar the middle 95%. Sort by lateral spread, by distance from the target line, or by both combined. The top row is the straightest.
- **Which club for this distance?** Enter a target distance and a tolerance (default ±3 m). The table lists the wedges and intents most likely to carry within that tolerance, with their mean carry, carry spread and lateral spread. It uses the shots of the ticked sessions.
- **Printed card.** See below.

A `*` after a name in the straightness plot and the distance table means there are fewer than 12 shots, so the numbers are less reliable.

### Stack tab

Progress of your stack training: club head speed per session, **one line per weight**. Each point is the average speed of all swings with that weight in that session. Heavy weights are red and light weights blue. The x-axis shows every ticked stack session; a weight that was not used in a session has no point there and its line continues across. Click a weight in the legend to hide or show its line, and hover a point for the number of swings and the 95% interval.

The weight is read from the `Club` column of the file (`235g` is 235 grams). Swings with a `Club` value that is not a weight are listed in an orange note and left out of the lines.

### Bag tab

Shows every club found in the swing data with its number of shots and last session. Click a club to put it on the full swing card (and in the Full swing tab) or take it off. The card order is fixed: driver, woods, hybrids, irons from low to high, then wedges. Press **Save bag**.

### Wedge intents tab

A grid of the wedges found in the pitching data against the intents (full, 11, 10, 9), with the number of shots in each cell. Click a cell to include that combination on the wedge card and in the Pitching tab. Click a wedge name to tick or untick its whole row. Cells without shots are greyed out. Press **Save selection**.

## Printed cards

Each of the Full swing and Pitching tabs has a **Generate card** button. The same cards come from `python -m golf cards`.

- The card uses **all shots of the ticked sessions** for the ticked clubs (and intents). To get a card of your current form, tick the last 4 weeks, or the last few sessions, on the Sessions tab first.
- Each bar shows the mean carry (dot and bold number), the middle 68% of shots (thin bar, the numbers above it) and the middle 95% (wide bar, the numbers below it). Mishits are included; they are part of what you will get on the course.
- A `*` after a club means there are fewer than 12 shots of it in your selection, so its numbers are less reliable. A footnote explains this.
- The title says how many sessions the card covers and from when to when.
- The wedge card lists the wedges in the order pw, gw, sw, lw, and within each wedge: full, 11, 10, 9. It also shows the average roll.
- The wind and height notes on the swing card are text from `golf.toml` (`[cards.swing]`).

Files are written to `Output/cards/<data folder>/`, for example `Output/cards/SwingData_Indoor/swing_distance_card.png` and `Output/cards/PitchingData_Indoor/wedge_distance_card.png`. That is the file to print. A copy named with the date of the last session (`2026-10-03_swing_distance_card.png`) is kept in the `archive` folder, so you can compare cards over time. A different data folder gets its own card folder.

From the command line:

```
python -m golf cards                     # uses your saved choices
python -m golf cards --as-of 2026-06-05  # leave out sessions after that date
```

## Adding a new club

1. In the FlightScope simulator, name the new club like the others: club, then the model or loft (`7 Iron 250`, `LW 60`). Add the intent suffix for reduced swings (`LW 60_9`).
2. Hit your session, export it and load it in the dashboard.
3. An orange note says the club was found but is not selected. Tick it on the **Bag** tab (swing) or the **Wedge intents** tab (wedges) and save.

If the name could not be read, the note says so. Fix the name in the simulator for next time, or add an alias in `golf.toml` (see [Data and settings](data-and-settings.md)).

## Troubleshooting

| Problem | What to do |
|---|---|
| The page says a folder is not loaded | Check the path, and that the folder contains `.csv` files directly (not only in subfolders; stack data may be one level down). |
| A tab is missing | Its folder is empty or could not be loaded: Full swing and Bag need the swing folder, Pitching and Wedge intents the pitching folder, Stack the stack folder. |
| "Port already in use" or an old page appears | Another dashboard is running. Close it, or start with `--port 8766`. |
| Browse seems to do nothing | The folder dialog may be behind the browser. You can also type the path and press Load data. |
| Many `*` on the card | Too few shots in the selected sessions. Tick more sessions on the Sessions tab. |
| Dashes in the review | A spread needs at least 2 shots. Historic columns show a dash when there are no historic shots for that choice of "Compare with". |
| A club is missing from a tab | It is not ticked on the Bag or Wedge intents tab, or it was not hit in the ticked sessions. |
| Want to start over | Close the dashboard and delete `golf.local.json`. The defaults from `golf.toml` apply again. |
