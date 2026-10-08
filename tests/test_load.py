from pathlib import Path

import pandas as pd
import pytest

from golf.bag import select_bag
from golf.config import BagSpec, load_config
from golf.data import load_shots, read_shot_file, unparsed_labels
from golf.data.labels import FULL_SWING, LabelParser

HEADER = "Index,Player,Time,Carry [m],Total [m],Total [m],Lateral [m],Club Speed [mph],Club Speed [mph],Club,Lateral Impact [mm],Shot Type"


def write_csv(path: Path, rows, header=HEADER):
    path.write_text("\n".join([header, *rows]) + "\n", encoding="windows-1252")
    return path


@pytest.fixture
def sample(tmp_path):
    return write_csv(tmp_path / "Pitching Lesson - 01012026 100000_windows-1252.csv", [
        "1,Me,2026-01-01; 10-00-01,100.0,103.87,103.9,5.0 R,80.0,80.0,GW 50,12,Fade",
        "2,Me,2026-01-01; 10-00-30,90.5,92.0,92.0,2.0 L,75.5,75.5,GW 50_9,-3,Draw",
        "3,Me,2026-01-01; 10-01-00,,,,,,,GW 50_10,,NotSet",
        "4,Me,2026-01-01; 10-02-00,50.0,55.0,55.0,0.0,60.0,60.0,Putter,,Straight",
    ])


def test_read_shot_file_schema_and_values(sample):
    shots = read_shot_file(sample, "pitching", LabelParser())

    assert len(shots) == 4
    first = shots.iloc[0]
    assert (first["club"], first["variant"], first["intent"], first["label"]) == ("gw", "50", FULL_SWING, "gw 50")
    assert first["carry_m"] == 100.0
    assert first["lateral_m"] == 5.0
    assert first["total_m"] == 103.87          # the more precise duplicate column wins
    assert str(first["session_date"]) == "2026-01-01"
    assert shots["lateral_m"].iloc[1] == -2.0
    assert shots["intent"].tolist() == [12, 9, 10, 12]


def test_shots_without_a_measurement_are_kept(sample):
    shots = read_shot_file(sample, "pitching", LabelParser())
    assert shots["carry_m"].isna().tolist() == [False, False, True, False]


def test_unparsed_labels_are_reported(sample):
    shots = read_shot_file(sample, "pitching", LabelParser())
    report = unparsed_labels(shots)
    assert report["raw_club"].tolist() == ["Putter"]
    assert report["shots"].tolist() == [1]


def test_load_shots_reads_only_top_level(tmp_path):
    write_csv(tmp_path / "a.csv", ["1,Me,2026-01-02; 10-00-01,100.0,1,1,1,80,80,7 Iron 245,1,Fade"])
    (tmp_path / "legacy data").mkdir()
    write_csv(tmp_path / "legacy data" / "b.csv", ["1,Me,2025-01-02; 10-00-01,100.0,1,1,1,80,80,7 Iron 245,1,Fade"])

    shots = load_shots("swing", directory=tmp_path)
    assert len(shots) == 1


def test_load_shots_sorts_chronologically(tmp_path):
    write_csv(tmp_path / "late.csv", ["1,Me,2026-03-01; 10-00-01,100.0,1,1,1,80,80,7 Iron 245,1,Fade"])
    write_csv(tmp_path / "early.csv", ["1,Me,2026-02-01; 10-00-01,100.0,1,1,1,80,80,7 Iron 245,1,Fade"])
    shots = load_shots("swing", directory=tmp_path)
    assert shots["session_date"].astype(str).tolist() == ["2026-02-01", "2026-03-01"]


def test_select_bag_filters_and_orders(sample):
    shots = read_shot_file(sample, "pitching", LabelParser())
    spec = BagSpec(clubs=("gw 50",), intents=(9, 12))
    selected = select_bag(shots, spec)
    assert selected["label"].tolist() == ["gw 50_9", "gw 50"]


def test_config_loads_and_resolves_paths():
    config = load_config()
    assert config.swing_dir.name == "Indoor" and config.swing_dir.is_absolute()
    assert config.bag["pitching"].intents == (9, 10, 11, 12)
    assert "maverick" in config.variant_aliases


# --- checks against the real data; skipped when the (git-ignored) data is absent ---------

@pytest.fixture(scope="module")
def real_config():
    config = load_config()
    if not any(config.swing_dir.glob("*.csv")):
        pytest.skip("real swing data not available")
    return config


@pytest.mark.parametrize("mode", ["swing", "pitching"])
def test_real_data_is_fully_understood(real_config, mode):
    shots = load_shots(mode, real_config)
    assert shots["timestamp"].notna().all(), "every shot needs a readable time"
    assert unparsed_labels(shots).empty, unparsed_labels(shots).to_string()
    assert shots["player"].nunique() == 1


def test_real_data_impact_units_are_consistent(real_config):
    shots = load_shots("swing", real_config)
    impact = shots["lateral_impact_mm"].dropna()
    if impact.empty:
        pytest.skip("no impact data")
    assert impact.abs().max() < 100, "values in cm would have been mixed with mm"


def test_unlisted_clubs_reports_new_clubs(sample):
    from golf.bag import unlisted_clubs

    shots = read_shot_file(sample, "pitching", LabelParser())
    assert unlisted_clubs(shots, BagSpec(clubs=("gw 50",))).empty
    report = unlisted_clubs(shots, BagSpec(clubs=("pw 241",)))
    assert report["club_variant"].tolist() == ["gw 50"]
    assert report["shots"].tolist() == [3]


def test_real_data_long_form_names_resolve_through_aliases(real_config):
    shots = load_shots("swing", real_config)
    assert shots["variant"].notna().all()
    assert {"gw 50", "lw 58", "sw 54", "pw 241", "5w ts2"} <= set(shots["club"] + " " + shots["variant"])
