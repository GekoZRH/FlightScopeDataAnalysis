import pytest

from golf.data.labels import FULL_SWING, LabelParser, build_label

parser = LabelParser(variant_aliases={"maverick": "maverik"})


@pytest.mark.parametrize(
    "raw, club, variant, intent",
    [
        ("7 Iron 245", "7i", "245", FULL_SWING),
        ("7 iron 245", "7i", "245", FULL_SWING),
        ("5 Wood", "5w", None, FULL_SWING),
        ("5W TS2", "5w", "ts2", FULL_SWING),
        ("4H Maverik", "4h", "maverik", FULL_SWING),
        ("4H Maverick", "4h", "maverik", FULL_SWING),
        ("Driver Ping", "driver", "ping", FULL_SWING),
        ("Driver Epic", "driver", "epic", FULL_SWING),
        ("2 iron MP-20 HBM", "2i", "mp-20 hbm", FULL_SWING),
        ("PW 241", "pw", "241", FULL_SWING),
        ("GW 50", "gw", "50", FULL_SWING),
        ("Gap Wedge", "gw", None, FULL_SWING),
        ("Pitching Wedge", "pw", None, FULL_SWING),
        ("GW 50_9", "gw", "50", 9),
        ("LW 58_10", "lw", "58", 10),
        ("SW 54_11", "sw", "54", 11),
        ("8 Iron 241_11", "8i", "241", 11),
        ("  8   Iron   245 ", "8i", "245", FULL_SWING),
    ],
)
def test_parse(raw, club, variant, intent):
    parsed = parser.parse(raw)
    assert (parsed.club, parsed.variant, parsed.intent) == (club, variant, intent)


@pytest.mark.parametrize("raw", ["", "Putter", "Mystery 9", None, float("nan")])
def test_unparsed_has_no_club(raw):
    assert parser.parse(raw).club is None


def test_digits_that_are_not_an_intent_stay_in_the_variant():
    parsed = parser.parse("2 iron mp_20")
    assert parsed.intent == FULL_SWING and parsed.variant == "mp_20"


def test_label_alias_is_applied_before_parsing():
    aliased = LabelParser(label_aliases={"gap wedge": "gw 50"})
    parsed = aliased.parse("Gap Wedge_9")
    assert (parsed.club, parsed.variant, parsed.intent) == ("gw", "50", 9)


@pytest.mark.parametrize(
    "club, variant, intent, label",
    [
        ("8i", "245", FULL_SWING, "8i 245"),
        ("driver", None, FULL_SWING, "driver"),
        ("gw", "50", 9, "gw 50_9"),
    ],
)
def test_build_label(club, variant, intent, label):
    assert build_label(club, variant, intent) == label


def test_label_matches_legacy_format():
    # The old scripts used labels such as "LW 58_9"; matching is case-insensitive.
    assert parser.parse("LW 58_9").label == "lw 58_9"
