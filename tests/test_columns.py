import numpy as np
import pandas as pd
import pytest

from golf.data.columns import METRIC_COLUMNS, parse_signed_direction, standardise_columns


def test_direction_signs():
    values = pd.Series(["4.5 R", "3.0 L", "0.0", "12R", " 2.5  l ", "-1.0", None, "abc", ""])
    result = parse_signed_direction(values).tolist()
    assert result[:6] == [4.5, -3.0, 0.0, 12.0, -2.5, -1.0]
    assert all(np.isnan(v) for v in result[6:])


def test_duplicate_headers_are_merged_and_first_wins():
    raw = pd.DataFrame({
        "Carry [m]": ["100.0", None],
        "Total [m]": ["103.87", None],
        "Total [m].1": ["103.9", "55.5"],
        "Club Speed [mph]": ["80.0", None],
        "Club Speed [mph].1": ["80.0", "70.0"],
    })
    out = standardise_columns(raw)
    assert out["total_m"].tolist() == [103.87, 55.5]
    assert out["club_speed_mph"].tolist() == [80.0, 70.0]


def test_impact_unit_is_converted_to_mm():
    in_cm = standardise_columns(pd.DataFrame({"Lateral Impact [cm]": ["1.5"]}))
    in_mm = standardise_columns(pd.DataFrame({"Lateral Impact [mm]": ["15"]}))
    assert in_cm["lateral_impact_mm"].iloc[0] == pytest.approx(15.0)
    assert in_mm["lateral_impact_mm"].iloc[0] == pytest.approx(15.0)


def test_other_unit_variants_of_a_known_name_are_ignored():
    raw = pd.DataFrame({"Roll [ft/s/ft]": ["9.9"], "Roll [m]": ["1.2"]})
    assert standardise_columns(raw)["roll_m"].iloc[0] == pytest.approx(1.2)


def test_missing_columns_are_filled_with_nan_and_schema_is_stable():
    out = standardise_columns(pd.DataFrame({"Carry [m]": ["10"]}))
    assert list(out.columns) == METRIC_COLUMNS
    assert out["spin_rpm"].isna().all()


def test_directional_columns_are_signed():
    raw = pd.DataFrame({"Lateral [m]": ["18.5 R"], "Club Path [deg]": ["6.8 L"]})
    out = standardise_columns(raw)
    assert out["lateral_m"].iloc[0] == 18.5
    assert out["club_path_deg"].iloc[0] == -6.8
