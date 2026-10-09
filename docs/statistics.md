# Statistics

How each number in the dashboard and on the cards is calculated, and what it can and cannot tell you. The settings mentioned are in `golf.toml` (see [Data and settings](data-and-settings.md)).

## The basics

- **Spread** always means the standard deviation (sd) of the shots, in the unit of the measure (metres, mph ...). A smaller spread means more consistent shots.
- **Mishits are never removed.** A shank or a thin shot is part of what you will get on the course. They widen the spread and, for carry, usually create a tail of short shots.
- **Lateral** is positive to the right and negative to the left of the target line.
- **Carry on the pitching tab** is simulated indoors on a mat. Treat its absolute values with care; club head speed is the more trustworthy measure there.

## Ranges: the middle 68% and 95%

Cards and the straightness plot show two ranges for each club:

| Range | Share of shots | For normally distributed shots it equals |
|---|---|---|
| thin bar | middle 68.27% | mean ± 1 standard deviation |
| wide bar | middle 95.45% | mean ± 2 standard deviations |

"Middle" means the same share of shots is left out on each side. For a lopsided distribution the ranges are lopsided too, which is why they are defined by share of shots rather than by standard deviations.

### Which distribution is used

The ranges come from a fitted distribution, not from the raw percentiles of the shots (there are too few shots for stable percentiles).

1. By default a **normal distribution** is fitted: the mean of the shots and their standard deviation (with the usual n−1).
2. A **skew-normal distribution** (a normal distribution that is stretched to one side) is used instead only if both hold:
   - the club has at least **25 shots** (`min_shots_skew`), and
   - a likelihood-ratio test says it fits significantly better than the normal one (`skew_alpha`, 0.05).
3. With fewer shots the normal distribution is used, because a skew fitted to a handful of shots is unreliable.

Carry of the longer clubs is typically skewed with a tail of short shots (a mishit does not fly further). In your data at the time of writing this holds from the driver down to the 8-iron 245, so their card ranges reach further below the mean than above it; the shorter clubs (8-iron 241 and the wedges) are described well by a normal distribution.

For the card, "mean" and "spread" are those of the fitted distribution; the median is that of the shots. With a skewed fit these can differ a little from the plain average and standard deviation in the review tables (typically less than 0.3 m).

## Per-session numbers and intervals

**Review tables** show plain statistics: the average and the standard deviation of the shots of the session, and of the historic shots (see the choices of "Compare with" in the [user guide](user-guide.md)). There is no test and no verdict there.

**Progress charts** show one point per session, the average (or the spread) of that session's shots, with a shaded **95% interval**:

- for an average: the usual t interval,
- for a spread: the interval based on the chi-square distribution.

Both assume roughly normal shots. A session needs at least 2 shots for a spread and its interval. How wide the intervals are is the main thing to watch:

| Shots in the session | 95% interval of the spread, as a multiple of the measured spread |
|---|---|
| 5 | about 0.6 to 2.9 |
| 10 | about 0.7 to 1.8 |
| 25 | about 0.8 to 1.4 |

So with 5 shots a session's spread can be far off. Compare lines and bands, not single points. Many sessions with a falling spread tell much more than one low value.

## Dispersion plot

The **rings** show where the middle 68% and 95% of the shots land, jointly in lateral and carry:

- Lateral and carry each get their own distribution (normal or skew-normal as above). They are joined by a Gaussian copula using the correlation of the two, so a link between lateral miss and carry (for example faster swings drifting right) is kept.
- The ring is the line of equal density that encloses the stated share of shots. It is found by sampling 40,000 points from the model, so it is smooth but not an exact formula; a fixed random seed makes it identical every time.
- A ring needs at least 5 shots (`min_shots_session`).

The labels **tighter / similar / broader** compare the spread of the session with that of the earlier shots, for carry and for lateral separately. The test is exact for small samples and assumes roughly normal shots: it takes the ratio of the two variances (an F test), turns the 95% interval of that ratio into an interval for the difference in spread, and says "tighter" or "broader" only when the whole interval is below or above zero. Each side needs at least 5 shots.

Read "similar" as "no difference that can be told from normal variation". With 5 to 10 shots only large changes are detected.

## Straightness and distance ladder (Pitching)

Both use all shots of the ticked sessions and the ticked wedges and intents.

- **Straightness.** For the lateral miss of each wedge and intent: mean (negative = left), the 68% and 95% ranges (distribution chosen as above), and the standard deviation. The sort options are the standard deviation, the size of the mean miss, or both together as √(mean² + sd²), the typical distance from the target line.
- **Which club for this distance.** For each wedge and intent with at least 3 shots, the carry distribution is fitted as above and the table gives the **probability that a shot carries within the tolerance of the target**. The best option is the one with the highest probability, which balances being close to the target on average and having a small spread. The lateral spread is shown next to it but does not enter the probability. The simulated carry caveat applies.

## Compare two measures (Pitching)

The optional **fit line** is an ordinary least-squares line through all plotted shots, and the note gives the **correlation r** (Pearson). The shots of all intents are pooled, so the line mostly reflects that harder swings go further; the relation within one intent can be flatter or even different. Use the colours to judge that.

## Garmin: results against sleep and training

**One number per session for the result.** Each result is reduced to one value per practice day:

- *Stack speed*: club head speed at one reference weight. Within a session the speed falls as the weight rises, so the session's slope of speed against weight is estimated from all its swings, and every session is moved to the reference weight (the weight used in most sessions; the heaviest if tied). This way a session where you used lighter weights does not look faster.
- *Full swing club head speed*: for each club the deviation of the session mean from the club's usual speed in per cent, averaged over the clubs hit that day (clubs seen in one session only are dropped). This way a day with more short irons is not 'slower'.
- *Full swing carry spread*: the standard deviation of carry of the session (at least 5 shots, at least 3 per club), as a per cent deviation from usual in the same way.

**Removing the trend.** With the switch on, 'usual' is not your overall mean but a straight line through the sessions in time (needs at least 4 sessions, otherwise the mean is used), so what remains is the day-to-day deviation from where you were heading. Without it, anything that changed slowly over the months, such as your speed, your gym routine or your sleep, will correlate with everything else. Example from real data: stack speed against 'strength training in the last 24 hours' was strongly negative without the trend removed, because the early (slower) sessions simply happened closer to training days.

**The correlation.** Pearson's r between the Garmin measure and the result over the sessions. The interval is the 95% interval from the Fisher z-transformation (`atanh(r)` plus or minus 1.96 / sqrt(n - 3)). With 8 sessions it is very wide (for r = 0.78 about 0.16 to 0.96). At least 5 sessions with a value are required, and a measure that never varies has no correlation. 'Clear' means that the interval does not contain zero.

**What it cannot tell you.** It is an association, not a cause. There are many measures and only a handful of sessions, so some will look clear by chance; the page shows how many to expect (number of measures times 0.05). Measures are not independent of each other (deep sleep goes with sleep duration), so two clear rows may be one effect. Practice sessions are not randomly scheduled either: you may practise more after a good night because you feel good.

**Garmin measures against each other.** The nightly table (`stats/daily.py`) has one row per night, dated by the day you woke up. Sleep, heart rate variability and overnight heart rate come from that night. Bedtime is the local clock hour of falling asleep, counted on after midnight (1 am is 25). Training measures add up strength or cardio activities that **ended before bedtime**, within 24 or 72 hours. A night without any such activity counts as 0 minutes, not as missing. The correlation and its interval are calculated as above, but with hundreds of nights the interval is narrow, so a 'clear' correlation can still be a weak one: look at r itself (r = 0.2 means the measure explains about 4% of the other's variation). The nights are not independent either (a bad week follows a bad week), so the interval is too optimistic, and no trend is removed here; the colour of the dots shows the date for that reason.

## Settings that change the numbers

| Setting | Effect |
|---|---|
| `min_shots` (12) | Cards mark clubs with fewer shots with a `*` |
| `min_shots_skew` (25), `skew_alpha` (0.05) | When a skewed distribution is used |
| `min_shots_session` (5) | Smallest session for rings and for tighter/broader labels |
| `ci_level` (0.95) | Level of the intervals in the progress charts and of the Garmin correlations |

## Things to keep in mind

- **Shots in one session are not independent.** Same day, same mat, same feel. The intervals assume independence, so the real uncertainty about your long-term level is larger than the bands suggest. This is another reason to look at many sessions.
- **Many clubs, many comparisons.** With 95% intervals, about one comparison in twenty will say "tighter" or "broader" by chance alone when you look at many clubs.
- **A club used rarely** has few shots and a wide band; the card marks it with `*`.
- **The selected sessions define the card.** A card of all sessions describes your average over a long time, a card of the last weeks describes your current form with fewer shots. Pick the sessions on the Sessions tab with that in mind.
