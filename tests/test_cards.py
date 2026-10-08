import numpy as np
import pandas as pd
import pytest

from golf.bag import select_bag
from golf.config import BagSpec, CardSpec, StatsSettings, load_config
from golf.report import draw_distance_card

SETTINGS = StatsSettings()


def make_card(statuses):
    rows = []
    for i, (label, status) in enumerate(statuses):
        mean = 200 - 20 * i
        rows.append({
            "label": label, "status": status, "window": "4w", "n": 15, "sessions": 3, "from": "2026-03-01", "as_of": "2026-10-03",
            "carry_mean": mean, "carry_lo68": mean - 5, "carry_hi68": mean + 5,
            "carry_lo95": mean - 10, "carry_hi95": mean + 10, "roll_mean": 1.5,
        })
    return pd.DataFrame(rows)


def texts(fig):
    return [t.get_text() for t in fig.axes[0].texts]


def test_card_marks_older_data_with_an_asterisk():
    card = make_card([("driver ping", "ok"), ("7i 245", "short"), ("pw 241", "ok")])
    fig = draw_distance_card(card, CardSpec(title="Test"), SETTINGS)
    labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
    assert labels == ["driver ping", "7i 245*", "pw 241"]


def test_first_row_is_at_the_top():
    card = make_card([("driver ping", "ok"), ("7i 245", "ok")])
    ax = draw_distance_card(card, CardSpec(title="Test"), SETTINGS).axes[0]
    assert ax.yaxis_inverted()
    assert [t.get_text() for t in ax.get_yticklabels()][0] == "driver ping"


def test_numbers_are_printed_for_each_bar():
    card = make_card([("driver ping", "ok")])
    printed = texts(draw_distance_card(card, CardSpec(title="Test"), SETTINGS))
    assert {"200", "195", "205", "190", "210"} <= set(printed)


def test_roll_only_when_requested():
    card = make_card([("gw 50", "ok")])
    assert not any("roll" in t for t in texts(draw_distance_card(card, CardSpec(title="T"), SETTINGS)))
    assert any("roll 1.5 m" in t for t in texts(draw_distance_card(card, CardSpec(title="T", show_roll=True), SETTINGS)))


def test_footnote_explains_only_the_markers_in_use():
    short = draw_distance_card(make_card([("a 1", "ok"), ("b 2", "short")]), CardSpec(title="T"), SETTINGS)
    assert "* fewer than 12 shots" in " ".join(t.get_text() for t in short.texts)
    fine = draw_distance_card(make_card([("a 1", "ok")]), CardSpec(title="T"), SETTINGS)
    assert "fewer than" not in " ".join(t.get_text() for t in fine.texts)


def test_title_names_the_sessions_used():
    card = make_card([("a 1", "ok")])
    title = draw_distance_card(card, CardSpec(title="Card"), SETTINGS).axes[0].get_title()
    assert title == "Card  (3 sessions, 2026-03-01 to 2026-10-03)"


def test_notes_are_drawn():
    fig = draw_distance_card(make_card([("a 1", "ok")]), CardSpec(title="T", notes=("hello wind",)), SETTINGS)
    assert "hello wind" in texts(fig)


def test_empty_card_is_rejected():
    with pytest.raises(ValueError):
        draw_distance_card(make_card([]).reindex(columns=make_card([("a 1", "ok")]).columns), CardSpec(title="T"), SETTINGS)


def test_card_can_be_saved(tmp_path):
    fig = draw_distance_card(make_card([("a 1", "ok"), ("b 2", "ok")]), CardSpec(title="T", xtick_step=25), SETTINGS)
    out = tmp_path / "card.png"
    fig.savefig(out, dpi=50)
    assert out.stat().st_size > 1000


def test_select_bag_full_swing_first_orders_wedge_intents():
    labels = ["pw 241", "pw 241_9", "pw 241_11", "pw 241_10", "gw 50_9", "gw 50"]
    parsed = [(l.split("_")[0], int(l.split("_")[1]) if "_" in l else 12) for l in labels]
    shots = pd.DataFrame({
        "club": [p[0].split()[0] for p in parsed], "variant": [p[0].split()[1] for p in parsed],
        "intent": pd.array([p[1] for p in parsed], dtype="Int64"), "label": labels,
        "timestamp": pd.Timestamp("2026-01-01"), "shot_index": range(len(labels)),
    })
    spec = BagSpec(clubs=("pw 241", "gw 50"), intents=(9, 10, 11, 12))
    assert select_bag(shots, spec, full_swing_first=True)["label"].tolist() == [
        "pw 241", "pw 241_11", "pw 241_10", "pw 241_9", "gw 50", "gw 50_9"]
    assert select_bag(shots, spec)["label"].tolist() == [
        "pw 241_9", "pw 241_10", "pw 241_11", "pw 241", "gw 50_9", "gw 50"]


def test_card_settings_are_read_from_the_config():
    config = load_config()
    assert config.cards["pitching"].show_roll and not config.cards["swing"].show_roll
    assert len(config.cards["swing"].notes) == 2
