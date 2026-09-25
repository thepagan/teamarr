"""Bare abbreviation pairs split into two sides (#821).

The separator extractor had a flat 3-character floor per side, so a two-letter
team code (TB, SF, KC, NY) came back as None: "TB vs DET" reached the matcher
with only DET, and "NY vs LA" lost both sides and fell through to TEAM_ONLY as
the single junk team "NY vs LA".
"""

import pytest

from teamarr.consumers.matching.classifier import (
    StreamCategory,
    classify_stream,
    extract_teams_from_separator,
    find_game_separator,
)


@pytest.mark.parametrize(
    ("stream", "team1", "team2"),
    [
        ("TB vs DET", "TB", "DET"),
        ("MLB 05: TB vs DET", "TB", "DET"),
        ("TB @ DET", "TB", "DET"),
        ("TB at DET", "TB", "DET"),
        ("MLB: TB vs. DET @ 07:10 PM ET", "TB", "DET"),
        ("NY vs LA", "NY", "LA"),
        ("COL at SF", "COL", "SF"),
        ("SF vs Seattle Mariners", "SF", "Seattle Mariners"),
    ],
)
def test_abbreviation_pairs_yield_both_sides(stream, team1, team2):
    c = classify_stream(stream)
    assert c.category == StreamCategory.TEAM_VS_TEAM
    assert (c.team1, c.team2) == (team1, team2)


@pytest.mark.parametrize("side", ["F1", "12", "-:", "É1"])
def test_non_code_two_char_sides_still_rejected(side):
    text = f"{side} vs Detroit Tigers"
    sep, pos = find_game_separator(text)
    team1, team2 = extract_teams_from_separator(text, sep, pos)
    assert team1 is None
    assert team2 == "Detroit Tigers"


def test_single_letter_side_still_rejected():
    text = "A vs Detroit Tigers"
    sep, pos = find_game_separator(text)
    assert extract_teams_from_separator(text, sep, pos) == (None, "Detroit Tigers")


def test_full_names_unchanged():
    c = classify_stream("Tampa Bay Rays vs Detroit Tigers")
    assert (c.team1, c.team2) == ("Tampa Bay Rays", "Detroit Tigers")
