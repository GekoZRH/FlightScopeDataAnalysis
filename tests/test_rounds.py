import numpy as np
import pandas as pd
import pytest

from golf.stats.rounds import ROUND_MEASURES, SUMMARY_ROWS, rolling_by_round, round_stats, summarise

PARS = [4, 5, 3, 4, 4, 3, 5, 4, 4, 4, 3, 5, 4, 4, 3, 4, 5, 4]            # 72, par 3 on holes 3, 6, 11, 15


def make_round(round_id, date, strokes, putts, fairways, penalties=None, rating=72.0, slope=130, pars=PARS):
    """One round as the two tables the loader makes. strokes, putts, fairways (HIT/LEFT/RIGHT/None), penalties: 18 values each."""
    start = pd.Timestamp(f"{date}T08:00:00Z")
    rounds = {"round_id": round_id, "start_utc": start, "date": start.date(), "course": "Test", "tee": "Weiss", "rating": rating, "slope": slope,
              "strokes": float(sum(strokes)), "par": float(sum(pars))}
    holes = [{"round_id": round_id, "hole": n + 1, "par": float(pars[n]), "stroke_index": n + 1, "strokes": float(strokes[n]),
              "putts": np.nan if putts[n] is None else float(putts[n]), "fairway": fairways[n],
              "penalties": np.nan if penalties is None or penalties[n] is None else float(penalties[n])} for n in range(18)]
    return rounds, holes


def tables(*made):
    rounds = pd.DataFrame([r for r, _ in made])
    holes = pd.DataFrame([h for _, hs in made for h in hs])
    return rounds, holes


def perfect_pars(first_date="2026-03-14"):
    return make_round(1, first_date, PARS, [2] * 18, ["HIT" if p > 3 else None for p in PARS])


def test_a_round_of_pars_with_two_putts_everywhere():
    s = round_stats(*tables(perfect_pars())).iloc[0]
    assert (s["strokes"], s["par"], s["to_par"]) == (72, 72, 0)
    assert s["differential"] == pytest.approx((72 - 72.0) * 113 / 130)
    assert s["fir_pct"] == 100 and s["gir_pct"] == 100 and s["putts_18"] == 36 and s["putts_per_hole"] == 2
    assert s["three_putt_pct"] == 0 and s["penalty_strokes"] == 0 and s["pars"] == 18 and s["birdies_or_better"] == 0


def test_fairways_count_only_par_four_and_five_with_an_outcome():
    fairways = ["HIT", "LEFT", None, "RIGHT", "HIT", None, "HIT", "HIT", "LEFT", "HIT", None, "HIT", "HIT", "HIT", None, "RIGHT", "HIT", "HIT"]
    s = round_stats(*tables(make_round(1, "2026-03-14", PARS, [2] * 18, fairways))).iloc[0]
    assert s["fw_holes"] == 14 and s["fw_hit"] == 10 and s["fir_pct"] == pytest.approx(100 * 10 / 14)


def test_a_fairway_outcome_on_a_par_three_is_not_a_fairway():
    fairways = ["HIT"] * 18
    s = round_stats(*tables(make_round(1, "2026-03-14", PARS, [2] * 18, fairways))).iloc[0]
    assert s["fw_holes"] == 14                                                            # the four par threes are not counted


def test_green_in_regulation_needs_strokes_minus_putts_at_most_par_minus_two():
    # hole 1 (par 4): 4 strokes, 2 putts -> on in 2: GIR. Hole 2 (par 5): 5 strokes, 2 putts -> on in 3: GIR.
    # Hole 3 (par 3): 4 strokes, 1 putt -> on in 3: no GIR, but a one putt for a bogey.
    strokes = [4, 5, 4] + PARS[3:]
    putts = [2, 2, 1] + [2] * 15
    s = round_stats(*tables(make_round(1, "2026-03-14", strokes, putts, [None] * 18))).iloc[0]
    assert s["gir_holes"] == 18 and s["gir"] == 17 and s["missed_green"] == 1 and s["scrambled"] == 0


def test_scrambling_is_par_or_better_after_missing_the_green():
    # hole 3 (par 3): 3 strokes with 1 putt -> missed the green (on in 2) and saved par
    strokes = [4, 5, 3] + PARS[3:]
    putts = [2, 2, 1] + [2] * 15
    s = round_stats(*tables(make_round(1, "2026-03-14", strokes, putts, [None] * 18))).iloc[0]
    assert s["missed_green"] == 1 and s["scrambled"] == 1 and np.isnan(s["scrambling_pct"])      # one chance is too few for a percentage


def test_scrambling_percentage_needs_enough_chances():
    strokes = [5, 6, 4, 5, 5, 4, 6, 5, 5, 5, 4, 6, 5, 5, 4, 5, 6, 5]                     # a bogey everywhere, all greens missed
    putts = [1] * 18
    s = round_stats(*tables(make_round(1, "2026-03-14", strokes, putts, [None] * 18))).iloc[0]
    assert s["missed_green"] == 18 and s["scrambled"] == 0 and s["scrambling_pct"] == 0 and s["bogeys"] == 18


def test_putting_counts_only_holes_with_putts():
    putts = [2, 3, None, 2, 1, 2, 2, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2]
    s = round_stats(*tables(make_round(1, "2026-03-14", PARS, putts, [None] * 18))).iloc[0]
    assert s["putt_holes"] == 17 and s["putts"] == 35 and s["putts_per_hole"] == pytest.approx(35 / 17)
    assert np.isnan(s["putts_18"])                                                        # a total per round needs all 18 holes
    assert s["three_putts"] == 2 and s["three_putt_pct"] == pytest.approx(100 * 2 / 17)


def test_too_few_holes_with_data_give_no_percentage():
    putts = [2] * 8 + [None] * 10
    fairways = ["HIT", None, None, None, None, None, None, None] + [None] * 10
    s = round_stats(*tables(make_round(1, "2026-03-14", PARS, putts, fairways))).iloc[0]
    assert np.isnan(s["gir_pct"]) and np.isnan(s["putts_per_hole"]) and np.isnan(s["fir_pct"])


def test_penalties_without_a_count_are_taken_as_none():
    penalties = [None, 2, None, 1] + [None] * 14
    s = round_stats(*tables(make_round(1, "2026-03-14", PARS, [2] * 18, [None] * 18, penalties))).iloc[0]
    assert s["penalty_strokes"] == 3


def test_score_types_are_counted():
    strokes = [3, 6, 3, 5, 4, 5, 4, 4, 6, 4, 3, 5, 4, 4, 3, 4, 5, 4]                    # birdie, bogey, par, bogey, par, double ...
    s = round_stats(*tables(make_round(1, "2026-03-14", strokes, [2] * 18, [None] * 18))).iloc[0]
    assert s["birdies_or_better"] == 2 + 0 and s["doubles_or_worse"] == 1 + 1 and s["bogeys"] == 2
    assert s["birdies_or_better"] + s["pars"] + s["bogeys"] + s["doubles_or_worse"] == 18


def test_rounds_come_back_oldest_first_with_the_differential():
    a = make_round(2, "2026-05-01", [p + 1 for p in PARS], [2] * 18, [None] * 18, rating=71.0, slope=125)
    b = make_round(1, "2026-03-01", PARS, [2] * 18, [None] * 18)
    s = round_stats(*tables(a, b))
    assert list(s["round_id"]) == [1, 2] and s.iloc[1]["differential"] == pytest.approx((90 - 71.0) * 113 / 125)


def test_a_round_without_par_still_has_its_score_and_putting():
    r, h = make_round(1, "2026-03-14", PARS, [2] * 18, [None] * 18)
    r["par"] = np.nan
    h = [dict(x, par=np.nan) for x in h]
    s = round_stats(pd.DataFrame([r]), pd.DataFrame(h)).iloc[0]
    assert np.isnan(s["to_par"]) and np.isnan(s["gir_pct"]) and s["putts_18"] == 36 and s["strokes"] == 72


# --- the overview ---------------------------------------------------------------------------------------

def two_rounds():
    a = make_round(1, "2025-01-10", PARS, [2] * 18, ["HIT"] * 4 + [None] * 14)                       # 4 fairways, all hit
    b = make_round(2, "2026-01-10", [p + 1 for p in PARS], [3] * 18, ["LEFT"] * 4 + [None] * 14)       # 4 fairways, all left; bogey golf
    return tables(a, b)


def test_the_overview_is_calculated_over_all_holes():
    rounds, holes = two_rounds()
    s = summarise(rounds, holes, [1, 2])
    assert s["rounds"] == 2 and s["strokes"] == pytest.approx(81) and s["to_par"] == pytest.approx(9)
    assert s["fir_pct"] == 50 and s["fir_left"] == 50 and s["fir_right"] == 0
    assert s["putts_per_hole"] == pytest.approx(2.5) and s["putts_18"] == pytest.approx(45) and s["three_putt_pct"] == 50
    assert s["par3"] == pytest.approx(0.5) and s["par4"] == pytest.approx(0.5) and s["par5"] == pytest.approx(0.5)


def test_the_overview_of_one_round_and_of_none():
    rounds, holes = two_rounds()
    assert summarise(rounds, holes, [1])["fir_pct"] == 100
    empty = summarise(rounds, holes, [])
    assert empty["rounds"] == 0 and empty["strokes"] is None


def test_every_overview_row_has_a_value_or_none():
    rounds, holes = two_rounds()
    s = summarise(rounds, holes, [1, 2])
    assert set(s) == {key for key, _, _ in SUMMARY_ROWS}


def test_measures_are_columns_of_the_statistics():
    stats = round_stats(*two_rounds())
    assert set(ROUND_MEASURES) <= set(stats.columns)


# --- averages over the last rounds ----------------------------------------------------------------------

def test_the_average_of_the_last_rounds_needs_enough_rounds():
    out = rolling_by_round(pd.Series([float(i) for i in range(1, 13)]))
    assert out["short"].isna().iloc[:2].all() and out["short"].iloc[2] == pytest.approx(2.0)          # 3 rounds are enough for the short average
    assert out["short"].iloc[11] == pytest.approx(10.0)                                              # rounds 8 to 12
    assert out["long"].isna().iloc[:4].all() and out["long"].iloc[4] == pytest.approx(3.0) and out["long"].iloc[11] == pytest.approx(7.5)


def test_a_round_without_a_value_has_no_average_and_is_skipped_in_the_next():
    values = pd.Series([1.0, 2.0, 3.0, np.nan, 5.0, 6.0, 7.0])
    out = rolling_by_round(values, windows=(3, 5), minimum=(3, 5))
    assert np.isnan(out["short"].iloc[3]) and out["short"].iloc[4] == pytest.approx(10 / 3)             # 2, 3 and 5
