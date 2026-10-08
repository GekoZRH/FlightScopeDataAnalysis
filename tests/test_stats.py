from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from golf.bag import select_bag
from golf.config import StatsSettings, load_config
from golf.data import load_shots
from golf.stats import (
    COVERAGE_1S, COVERAGE_2S, card_table, compare_groups, describe, fit_bivariate,
    fit_univariate, mean_ci, rolling_sessions, sd_ci, session_summary,
)

SETTINGS = StatsSettings()


# --- univariate ------------------------------------------------------------------

def test_coverage_constants_match_one_and_two_sigma():
    assert COVERAGE_1S == pytest.approx(0.682689, abs=1e-6)
    assert COVERAGE_2S == pytest.approx(0.954500, abs=1e-6)


def test_normal_ranges_are_mean_plus_minus_sigma():
    x = np.random.default_rng(1).normal(100, 8, 60)
    fit = fit_univariate(x)
    lo, hi = fit.interval(COVERAGE_1S)
    assert fit.kind == "normal"
    assert lo == pytest.approx(x.mean() - x.std(ddof=1), abs=1e-6)
    assert hi == pytest.approx(x.mean() + x.std(ddof=1), abs=1e-6)
    lo2, hi2 = fit.interval(COVERAGE_2S)
    assert hi2 - lo2 == pytest.approx(4 * x.std(ddof=1), abs=1e-6)


def test_skew_is_detected_with_enough_shots():
    x = stats.skewnorm.rvs(-6, loc=150, scale=12, size=400, random_state=3)   # mishits fall short
    fit = fit_univariate(x)
    lo, hi = fit.interval(COVERAGE_2S)
    assert fit.kind == "skewnorm" and fit.shape < 0 and fit.p_skew < 0.05
    assert fit.mean - lo > hi - fit.mean, "long tail towards short shots"


def test_skew_is_not_fitted_to_few_shots():
    x = stats.skewnorm.rvs(-6, loc=150, scale=12, size=15, random_state=3)
    assert fit_univariate(x).kind == "normal"


def test_normal_data_stays_normal():
    kinds = [fit_univariate(np.random.default_rng(s).normal(0, 1, 60)).kind for s in range(40)]
    assert kinds.count("skewnorm") <= 5            # about the 5% false-positive rate


def test_constant_values_do_not_break_the_fit():
    fit = fit_univariate([5.0, 5.0, 5.0])
    assert fit.mean == 5.0 and fit.interval(COVERAGE_1S)[0] == pytest.approx(5.0, abs=1e-6)


def test_too_few_values_raise():
    with pytest.raises(ValueError):
        fit_univariate([1.0])


def test_prob_between():
    fit = fit_univariate(np.random.default_rng(0).normal(50, 4, 200))
    assert fit.prob_between(fit.mean - fit.sd, fit.mean + fit.sd) == pytest.approx(COVERAGE_1S, abs=1e-6)


# --- bivariate -------------------------------------------------------------------

def test_correlation_is_recovered():
    rng = np.random.default_rng(5)
    z = rng.multivariate_normal([0, 0], [[1, 0.6], [0.6, 1]], size=800)
    fit = fit_bivariate(z[:, 0] * 3, 120 + z[:, 1] * 7)
    assert fit.rho == pytest.approx(0.6, abs=0.06)


def test_density_level_matches_the_normal_ellipse():
    rng = np.random.default_rng(6)
    x, y = rng.normal(0, 3, 500), rng.normal(100, 7, 500)
    fit = fit_bivariate(x, y)
    # for an uncorrelated normal, the region holding `c` of the shots ends at density (1-c)/(2*pi*sx*sy)
    sx, sy = fit.x.sd, fit.y.sd
    expected = (1 - 0.68) / (2 * np.pi * sx * sy * np.sqrt(1 - fit.rho ** 2))
    assert fit.density_level(0.68) == pytest.approx(expected, rel=0.05)


def test_bivariate_drops_incomplete_pairs():
    fit = fit_bivariate([1, 2, np.nan, 4, 5], [10, 11, 12, np.nan, 14])
    assert fit.x.n == 3


# --- intervals -------------------------------------------------------------------

@pytest.mark.parametrize("interval, truth", [(mean_ci, 100.0), (sd_ci, 8.0)])
def test_small_sample_intervals_have_the_stated_coverage(interval, truth):
    rng = np.random.default_rng(11)
    hits = 0
    runs = 1500
    for _ in range(runs):
        low, high = interval(rng.normal(100, 8, 8), 0.95)
        hits += low <= truth <= high
    assert 0.93 < hits / runs < 0.97


def test_intervals_with_one_value_are_nan():
    assert np.isnan(mean_ci([3.0])[0]) and np.isnan(sd_ci([3.0])[1])


# --- comparing periods -----------------------------------------------------------

def test_tighter_spread_is_detected():
    rng = np.random.default_rng(2)
    result = compare_groups(rng.normal(0, 1, 40), rng.normal(0, 2, 40))
    assert result.direction == -1 and result.high < 1


def test_no_change_is_not_called_a_change():
    rng = np.random.default_rng(3)
    result = compare_groups(rng.normal(0, 2, 40), rng.normal(0, 2, 40))
    assert result.direction == 0 and result.low < 1 < result.high


def test_too_few_shots_give_no_verdict():
    assert compare_groups([1, 2, 3], [1, 2, 3, 4, 5, 6, 7, 8, 9]).direction is None


def test_difference_of_means():
    rng = np.random.default_rng(4)
    result = compare_groups(rng.normal(110, 5, 50), rng.normal(100, 5, 50), np.mean, ratio=False)
    assert result.direction == 1 and result.estimate == pytest.approx(10, abs=3)


# --- test data ---------------------------------------------------------------------

def make_shots(spec):
    """spec: list of (label, days_ago, count); as-of day is 2026-06-30."""
    base = date(2026, 6, 30)
    rng = np.random.default_rng(0)
    rows = []
    for label, days_ago, count in spec:
        day = base - timedelta(days=days_ago)
        for i in range(count):
            club, _, rest = label.partition(" ")
            rows.append({
                "label": label, "club": club, "variant": rest.split("_")[0], "intent": 12,
                "session_date": day, "timestamp": pd.Timestamp(day) + pd.Timedelta(minutes=i),
                "shot_index": i, "carry_m": 100 + rng.normal(0, 5), "lateral_m": rng.normal(0, 3),
            })
    return pd.DataFrame(rows)


# --- per session -----------------------------------------------------------------

def test_session_summary_values():
    shots = make_shots([("a 1", 0, 10), ("a 1", 7, 6)])
    summary = session_summary(shots, "carry_m")
    assert len(summary) == 2
    last = summary.iloc[-1]
    group = shots[shots["session_date"] == last["session_date"]]["carry_m"]
    assert last["n"] == 10 and last["mean"] == pytest.approx(group.mean())
    assert last["sd"] == pytest.approx(group.std(ddof=1))
    assert last["sd_lo"] < last["sd"] < last["sd_hi"]


def test_session_with_one_shot_has_no_spread():
    summary = session_summary(make_shots([("a 1", 0, 1)]), "carry_m")
    assert np.isnan(summary["sd"].iloc[0]) and np.isnan(summary["sd_lo"].iloc[0])


def test_rolling_pools_the_last_sessions():
    shots = make_shots([("a 1", 21, 5), ("a 1", 14, 5), ("a 1", 7, 5), ("a 1", 0, 5)])
    rolling = rolling_sessions(shots, "carry_m", window_sessions=3)
    assert rolling["n"].tolist() == [5, 10, 15, 15]
    assert rolling["sessions_in_window"].tolist() == [1, 2, 3, 3]


# --- card ------------------------------------------------------------------------

def test_describe_reports_nan_for_too_few_shots():
    result = describe([4.0], SETTINGS)
    assert result["n"] == 1 and np.isnan(result["mean"])


def test_card_table_columns_and_status():
    shots = make_shots([("a 1", 0, 14), ("b 2", 0, 3), ("c 3", 0, 4), ("c 3", 200, 20)])
    card = card_table(shots, SETTINGS).set_index("label")
    assert card.loc["a 1", "status"] == "ok" and card.loc["b 2", "status"] == "short"
    assert card.loc["c 3", "status"] == "ok" and card.loc["c 3", "n"] == 24     # all given shots are used
    assert card.loc["a 1", "carry_lo68"] < card.loc["a 1", "carry_mean"] < card.loc["a 1", "carry_hi68"]
    assert card.loc["a 1", "carry_lo95"] < card.loc["a 1", "carry_lo68"]
    assert card.loc["a 1", "n"] == 14


def test_card_table_describes_the_span_of_the_selection():
    shots = make_shots([("a 1", 0, 12), ("a 1", 21, 12), ("b 2", 7, 12)])
    card = card_table(shots, SETTINGS)
    assert set(card["sessions"]) == {3} and set(card["as_of"]) == {date(2026, 6, 30)} and set(card["from"]) == {date(2026, 6, 9)}


def test_card_table_can_stop_at_a_date():
    shots = make_shots([("a 1", 0, 12), ("a 1", 21, 12)])
    card = card_table(shots, SETTINGS, as_of=date(2026, 6, 20))
    assert card["n"].tolist() == [12] and card["as_of"].iloc[0] == date(2026, 6, 9)


def test_card_table_ignores_shots_without_measurements():
    shots = make_shots([("a 1", 0, 14)])
    shots.loc[:5, "carry_m"] = np.nan
    assert card_table(shots, SETTINGS)["n"].tolist() == [8]


def test_card_table_of_nothing_is_empty():
    shots = make_shots([("a 1", 0, 3)])
    shots["carry_m"] = np.nan
    assert card_table(shots, SETTINGS).empty


def test_card_rows_follow_the_order_of_the_input():
    shots = make_shots([("z 9", 0, 12), ("a 1", 0, 12), ("m 5", 0, 12)])
    assert card_table(shots, SETTINGS)["label"].tolist() == ["z 9", "a 1", "m 5"]


# --- real data -------------------------------------------------------------------

@pytest.fixture(scope="module")
def real():
    config = load_config()
    if not any(config.swing_dir.glob("*.csv")):
        pytest.skip("real data not available")
    return config


@pytest.mark.parametrize("mode", ["swing", "pitching"])
def test_card_on_real_data(real, mode):
    shots = select_bag(load_shots(mode, real), real.bag[mode])
    card = card_table(shots, real.stats)
    assert not card.empty
    assert (card["carry_lo95"] < card["carry_lo68"]).all() and (card["carry_hi68"] < card["carry_hi95"]).all()
    assert (card[card["status"] == "ok"]["n"] >= real.stats.min_shots).all()


# --- exact small-sample comparison ---------------------------------------------------

def test_exact_comparison_has_the_stated_coverage():
    from golf.stats import compare_normal

    rng = np.random.default_rng(21)
    hits_sd = hits_mean = 0
    runs = 1500
    for _ in range(runs):
        session, before = rng.normal(100, 6, 6), rng.normal(100, 6, 24)
        c = compare_normal(session, before, "sd")
        hits_sd += c.low <= 0 <= c.high
        m = compare_normal(session, before, "mean")
        hits_mean += m.low <= 0 <= m.high
    assert 0.93 < hits_sd / runs < 0.97
    assert 0.93 < hits_mean / runs < 0.97


def test_exact_comparison_finds_real_changes_and_ignores_noise():
    from golf.stats import compare_normal

    rng = np.random.default_rng(22)
    tighter = compare_normal(rng.normal(0, 1, 12), rng.normal(0, 3, 30), "sd")
    assert tighter.direction == -1 and tighter.estimate < 0 and tighter.high < 0
    recent, before = rng.normal(110, 3, 12), rng.normal(100, 3, 30)
    longer = compare_normal(recent, before, "mean")
    assert longer.direction == 1 and longer.estimate == pytest.approx(recent.mean() - before.mean())
    same = compare_normal(rng.normal(0, 3, 12), rng.normal(0, 3, 30), "sd")
    assert same.low < 0 < same.high


def test_exact_comparison_needs_enough_shots():
    from golf.stats import compare_normal

    assert compare_normal([1, 2, 3, 4], list(range(30)), "sd").direction is None
