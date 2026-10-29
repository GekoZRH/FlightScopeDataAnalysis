from pathlib import Path

import numpy as np
import pytest

from golf.config import DEFAULT_CONFIG
from golf.targets import DELIVERY_FILE, LAUNCH_FILE, LOFT_FILE, SPIN_FILE, Targets, load_targets

REPO_TARGETS = DEFAULT_CONFIG.parent / "targets"

LAUNCH = """# comment lines are ignored
ball_speed_mph,-2,0,2
100,10.0,12.0,14.0
120,8.0,10.0,12.0
"""
SPIN = """ball_speed_mph,-2,0,2
100,2800,2600,2400
120,3000,2800,2600
"""
DELIVERY = """
[attack_angle]
driver = [2.0, 5.0]
"7i" = [-5, -3]
"8i 241" = [-6.5, -4.5]

[club_path]
default = [-2.0, 2.0]
driver = [-3.0, 1.0]

[face_to_path]
default = [-2.0, 2.0]
"""
LOFT = """
[dynamic_loft]
"7i 245" = [26.5, 29.5]
"""


def write(folder: Path, *, launch=LAUNCH, spin=SPIN, delivery=DELIVERY, loft=LOFT) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in ((LAUNCH_FILE, launch), (SPIN_FILE, spin), (DELIVERY_FILE, delivery), (LOFT_FILE, loft)):
        if text is not None:
            (folder / name).write_text(text, encoding="utf-8")
    return folder


# --- the files you edit -----------------------------------------------------------------------------------

def test_all_four_files_are_read(tmp_path):
    t = load_targets(write(tmp_path / "t"))
    assert t.notes == [] and t.chart is not None and t.chart.launch.shape == (2, 3)
    assert t.attack_angle["driver"] == (2.0, 5.0) and t.attack_angle["7i"] == (-5.0, -3.0) and t.dynamic_loft["7i 245"] == (26.5, 29.5)


def test_a_club_finds_its_range_by_variant_then_club_then_default(tmp_path):
    t = load_targets(write(tmp_path / "t"))
    assert t.band("attack_angle", "8i 241") == (-6.5, -4.5)            # the variant wins
    assert t.band("attack_angle", "7i 245") == (-5.0, -3.0)            # else the club
    assert t.band("attack_angle", "putter") is None                    # no default for the attack angle
    assert t.band("club_path", "7i 245") == (-2.0, 2.0) and t.band("club_path", "driver ping") == (-3.0, 1.0)
    assert t.band("face_to_path", "pw 241") == (-2.0, 2.0)
    assert t.band("dynamic_loft", "7i 245") == (26.5, 29.5) and t.band("dynamic_loft", "7i 241") is None


def test_clubs_are_matched_without_regard_to_case(tmp_path):
    t = load_targets(write(tmp_path / "t", delivery='[attack_angle]\n"7I" = [-5, -3]\n'))
    assert t.band("attack_angle", "7i 245") == (-5.0, -3.0)


def test_no_folder_is_not_an_error(tmp_path):
    t = load_targets(None)
    assert t.notes == [] and t.chart is None and t.band("attack_angle", "driver") is None
    missing = load_targets(tmp_path / "nowhere")
    assert missing.chart is None and "does not exist" in missing.notes[0]


def test_a_missing_file_is_a_note_and_the_rest_still_works(tmp_path):
    t = load_targets(write(tmp_path / "t", delivery=None))
    assert [n for n in t.notes] == [f"{DELIVERY_FILE} not found in {tmp_path / 't'}"] and t.chart is not None and t.dynamic_loft
    t = load_targets(write(tmp_path / "u", launch=None))
    assert t.chart is None and LAUNCH_FILE in t.notes[0] and t.attack_angle


def test_a_broken_toml_file_is_a_note(tmp_path):
    t = load_targets(write(tmp_path / "t", delivery="[attack_angle\ndriver = "))
    assert t.attack_angle == {} and "could not be read" in t.notes[0] and t.dynamic_loft


def test_wrong_ranges_are_reported_one_by_one(tmp_path):
    t = load_targets(write(tmp_path / "t", delivery='[attack_angle]\ndriver = [5.0, 2.0]\n"3w" = [1]\n"5w" = ["a", "b"]\n"7i" = [-5, -3]\n'))
    assert t.attack_angle == {"7i": (-5.0, -3.0)}
    assert len(t.notes) == 3 and "must be below" in t.notes[0] and "two numbers" in t.notes[1] and "two numbers" in t.notes[2]


def test_a_grid_with_problems_is_refused(tmp_path):
    cases = {
        "empty cell": ("ball_speed_mph,-2,0,2\n100,10.0,,14.0\n120,8.0,10.0,12.0\n", "empty cells"),
        "text": ("ball_speed_mph,-2,0,2\n100,10.0,x,14.0\n120,8.0,10.0,12.0\n", "could not be read"),
        "one row": ("ball_speed_mph,-2,0,2\n100,10.0,12.0,14.0\n", "at least two"),
        "twice": ("ball_speed_mph,-2,0,2\n100,10.0,12.0,14.0\n100,8.0,10.0,12.0\n", "twice"),
    }
    for name, (text, message) in cases.items():
        t = load_targets(write(tmp_path / name.replace(" ", "_"), launch=text))
        assert t.chart is None and any(message in n for n in t.notes), name


def test_launch_and_spin_must_have_the_same_axes(tmp_path):
    t = load_targets(write(tmp_path / "t", spin="ball_speed_mph,-2,0,4\n100,2800,2600,2400\n120,3000,2800,2600\n"))
    assert t.chart is None and "same ball speeds" in t.notes[0]


def test_the_rows_and_columns_may_be_in_any_order(tmp_path):
    shuffled = "ball_speed_mph,2,-2,0\n120,12.0,8.0,10.0\n100,14.0,10.0,12.0\n"
    t = load_targets(write(tmp_path / "t", launch=shuffled, spin="ball_speed_mph,2,-2,0\n120,2600,3000,2800\n100,2400,2800,2600\n"))
    launch, spin = t.chart.lookup(100, -2)
    assert launch[0] == pytest.approx(10.0) and spin[0] == pytest.approx(2800) and list(t.chart.speeds) == [100.0, 120.0]


# --- looking up the chart ---------------------------------------------------------------------------------

def chart(tmp_path):
    return load_targets(write(tmp_path / "t")).chart


def test_a_grid_point_gives_its_value(tmp_path):
    c = chart(tmp_path)
    launch, spin = c.lookup([100, 120], [0, 2])
    assert list(launch) == pytest.approx([12.0, 12.0]) and list(spin) == pytest.approx([2600, 2600])


def test_between_grid_points_it_is_interpolated(tmp_path):
    launch, spin = chart(tmp_path).lookup(110, 1)
    assert launch[0] == pytest.approx(np.mean([12.0, 14.0, 10.0, 12.0])) and spin[0] == pytest.approx(np.mean([2600, 2400, 2800, 2600]))


def test_outside_the_chart_the_edge_value_is_used(tmp_path):
    c = chart(tmp_path)
    assert c.lookup(300, 40)[0][0] == pytest.approx(c.lookup(120, 2)[0][0]) and c.lookup(10, -40)[1][0] == pytest.approx(c.lookup(100, -2)[1][0])


# --- the files of this project -----------------------------------------------------------------------------

def test_the_shipped_chart_is_complete_and_smooth():
    t = load_targets(REPO_TARGETS)
    assert t.notes == [] and t.chart is not None
    c = t.chart
    assert c.launch.shape == (13, 11) and list(c.speeds) == list(range(80, 201, 10)) and list(c.aoas) == list(range(-10, 11, 2))
    assert (np.diff(c.launch, axis=1) > 0).all()                       # more launch with a higher angle of attack
    assert (np.diff(c.launch, axis=0) < 0).all()                       # less launch with a higher ball speed
    assert (np.diff(c.spin, axis=1) <= 0).all()                        # less spin with a higher angle of attack
    assert np.abs(np.diff(c.launch, 2, axis=1)).max() < 1.0 and np.abs(np.diff(c.spin, 2, axis=1)).max() <= 150


def test_a_few_cells_of_the_shipped_chart_match_the_picture():
    c = load_targets(REPO_TARGETS).chart
    assert c.lookup(150, 0)[0][0] == pytest.approx(12.4) and c.lookup(150, 0)[1][0] == pytest.approx(2600)
    assert c.lookup(100, 10)[0][0] == pytest.approx(22.6) and c.lookup(80, -10)[1][0] == pytest.approx(2800)
    assert c.lookup(200, 10)[1][0] == pytest.approx(1750) and c.lookup(120, 4)[0][0] == pytest.approx(17.4)


def test_the_shipped_ranges_cover_the_bag():
    t = load_targets(REPO_TARGETS)
    for club in ("driver", "3w", "5w", "4i", "7i", "9i", "pw", "gw", "sw", "lw"):
        low, high = t.band("attack_angle", club)
        assert low < high
    assert t.band("attack_angle", "driver ping")[0] > 0 > t.band("attack_angle", "7i 245")[1]       # up with the driver, down with the irons
    assert t.band("club_path", "anything") == (-2.0, 2.0) and t.band("face_to_path", "anything") == (-2.0, 2.0)
    assert t.band("dynamic_loft", "7i 245") is not None and t.band("dynamic_loft", "driver ping") is not None


def test_the_targets_object_is_empty_by_default():
    assert Targets().band("attack_angle", "driver") is None
