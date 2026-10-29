import pytest

from golf.dashboard import api
from golf.stats.intervals import wilson_interval
from golf.targets import Targets, load_targets

from test_dashboard import call, state  # noqa: F401  (fixture)
from test_levers import lever_state  # noqa: F401  (fixture: swing shots with attack angle, loft, path and face to path)
from test_targets import DELIVERY, LOFT, write


@pytest.fixture
def banded(lever_state, tmp_path):
    lever_state.targets = load_targets(write(tmp_path / "targets"))
    return lever_state


def shots_of(state, label):
    return state.selected("swing").query("label == @label")


# --- the band in the progress charts ----------------------------------------------------------------------

def test_a_measure_with_a_target_range_returns_it_with_the_share_inside(banded):
    d = call(banded, "/api/swing/series", label="driver ping", measure="aoa")
    t = d["target"]
    values = shots_of(banded, "driver ping")["aoa_deg"]
    assert (t["low"], t["high"]) == (2.0, 5.0) and t["shots"] == len(values)
    assert t["in_range"] == pytest.approx(100 * ((values >= 2) & (values <= 5)).mean())
    latest = shots_of(banded, "driver ping")
    latest = latest[latest["session_date"] == latest["session_date"].max()]["aoa_deg"]
    assert t["in_range_last"] == pytest.approx(100 * ((latest >= 2) & (latest <= 5)).mean()) and t["last_session"] == str(shots_of(banded, "driver ping")["session_date"].max())


def test_the_variant_wins_over_the_club_and_the_default_covers_the_rest(banded):
    assert call(banded, "/api/swing/series", label="7i 245", measure="aoa")["target"]["low"] == -5.0          # "7i" covers the 7-iron
    path = call(banded, "/api/swing/series", label="7i 245", measure="club_path")["target"]
    assert (path["low"], path["high"]) == (-2.0, 2.0)                                                          # the default
    assert call(banded, "/api/swing/series", label="driver ping", measure="club_path")["target"]["low"] == -3.0   # the driver has its own
    assert call(banded, "/api/swing/series", label="7i 245", measure="face_to_path")["target"]["high"] == 2.0
    assert call(banded, "/api/swing/series", label="7i 245", measure="dynamic_loft")["target"]["low"] == 26.5


def test_a_club_without_a_range_and_a_measure_without_one_have_no_target(banded):
    assert "target" not in call(banded, "/api/swing/series", label="gw 50", measure="aoa")                   # no range for the gap wedge
    assert "target" not in call(banded, "/api/swing/series", label="7i 245", measure="carry_mean")
    assert "target" not in call(banded, "/api/swing/series", label="7i 245", measure="spin_loft")


def test_pitching_charts_have_no_bands(banded):
    assert "target" not in call(banded, "/api/pitching/series", label="gw 50", measure="carry_mean")
    with pytest.raises(api.ApiError, match="Unknown measure"):
        call(banded, "/api/pitching/series", label="gw 50", measure="aoa_in_range")


def test_face_to_path_is_a_measure_of_its_own(banded):
    d = call(banded, "/api/swing/series", label="7i 245", measure="face_to_path")
    assert d["title"].startswith("Face to path") and len(d["sessions"]) == 6


# --- the share of shots inside the range ------------------------------------------------------------------

def test_the_share_per_session_with_its_interval(banded):
    d = call(banded, "/api/swing/series", label="7i 245", measure="aoa_in_range")
    assert d["percent"] is True and d["title"].startswith("Angle of attack within the target range") and len(d["sessions"]) == 6
    shots = shots_of(banded, "7i 245")
    first = d["sessions"][0]
    day = shots[shots["session_date"].astype(str) == first["date"]]["aoa_deg"]
    hits = int(((day >= -5) & (day <= -3)).sum())
    lo, hi = wilson_interval(hits, len(day), 0.95)
    assert first["n"] == len(day) and first["y"] == pytest.approx(100 * hits / len(day)) and (first["lo"], first["hi"]) == pytest.approx((lo, hi))
    assert all(0 <= s["y"] <= 100 and s["lo"] <= s["y"] <= s["hi"] for s in d["sessions"])


def test_a_club_without_a_range_says_so_instead_of_drawing(banded):
    d = call(banded, "/api/swing/series", label="gw 50", measure="aoa_in_range")
    assert d["sessions"] == [] and "No target range for gw 50" in d["note"]


def test_the_menu_offers_the_ranges_for_full_swings_only(banded):
    swing = call(banded, "/api/swing/overview")["measures"]
    keys = {m["key"] for m in swing}
    assert {"aoa_in_range", "club_path_in_range", "face_to_path_in_range", "dynamic_loft_in_range", "face_to_path"} <= keys
    assert {m["group"] for m in swing if m["key"].endswith("_in_range")} == {"Target ranges"}
    assert not {m["key"] for m in call(banded, "/api/pitching/overview")["measures"]} & {"aoa_in_range", "dynamic_loft_in_range"}


def test_editing_the_files_changes_the_band_after_loading(banded, tmp_path):
    folder = tmp_path / "targets"
    (folder / "delivery_ranges.toml").write_text(DELIVERY.replace("driver = [2.0, 5.0]", "driver = [3.0, 6.0]"), encoding="utf-8")
    banded.targets = load_targets(folder)
    assert call(banded, "/api/swing/series", label="driver ping", measure="aoa")["target"]["low"] == 3.0


# --- the files in the dataset list ------------------------------------------------------------------------

def test_the_target_folder_and_its_problems_are_listed(state, tmp_path):
    info = call(state, "/api/state")["datasets"]["targets"]
    assert info["enabled"] is True and info["loaded"] is False and any("does not exist" in n for n in info["notes"])    # the test config has no such folder
    state.targets = load_targets(write(tmp_path / "targets", loft="[dynamic_loft\n"))
    info = call(state, "/api/state")["datasets"]["targets"]
    assert info["loaded"] is True and any("dynamic_loft_ranges.toml could not be read" in n for n in info["notes"])


def test_an_empty_target_setting_turns_the_files_off(state):
    import dataclasses
    state.config = dataclasses.replace(state.config, targets_dir=None)
    assert call(state, "/api/state")["datasets"]["targets"] == {"folder": "", "enabled": False, "loaded": False, "notes": [], "error": ""}
