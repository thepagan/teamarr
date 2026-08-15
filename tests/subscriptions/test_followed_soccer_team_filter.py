"""Follow-Teams soccer subscriptions only emit the followed clubs' events."""

from types import SimpleNamespace
from unittest.mock import patch

from teamarr.consumers.event_group_processor.team_filter import TeamFiltering
from tests.fakes import FakeGroup, FakeSubscription


def _event(event_id: str, sport: str, home_id: str, away_id: str) -> dict:
    def team(team_id: str):
        return SimpleNamespace(id=team_id, provider="espn")

    return {
        "event": SimpleNamespace(
            id=event_id,
            provider="espn",
            sport=sport,
            home_team=team(home_id),
            away_team=team(away_id),
        )
    }


def test_global_followed_team_filters_other_soccer_clubs_but_not_other_sports():
    processor = TeamFiltering()
    matches = [
        _event("followed-home", "soccer", "10", "20"),
        _event("followed-away", "soccer", "30", "10"),
        _event("other-soccer", "soccer", "30", "40"),
        _event("other-sport", "basketball", "30", "40"),
    ]
    subscription = FakeSubscription(
        soccer_mode="teams",
        soccer_followed_teams=[{"provider": "espn", "team_id": "10"}],
    )

    with patch(
        "teamarr.database.subscription.get_subscription", return_value=subscription
    ):
        kept, count = processor._filter_by_followed_soccer_teams(
            matches, FakeGroup(), SimpleNamespace()
        )

    assert [match["event"].id for match in kept] == [
        "followed-home",
        "followed-away",
        "other-sport",
    ]
    assert count == 1


def test_group_followed_team_override_takes_priority_over_global_subscription():
    processor = TeamFiltering()
    matches = [
        _event("global-team", "soccer", "10", "20"),
        _event("group-team", "soccer", "50", "60"),
    ]
    group = FakeGroup(
        subscription_leagues=[],
        subscription_soccer_mode="teams",
        subscription_soccer_followed_teams=[{"provider": "espn", "team_id": "50"}],
    )

    kept, count = processor._filter_by_followed_soccer_teams(
        matches, group, SimpleNamespace()
    )

    assert [match["event"].id for match in kept] == ["group-team"]
    assert count == 1


def test_manual_soccer_mode_does_not_filter_events():
    processor = TeamFiltering()
    matches = [_event("other-soccer", "soccer", "30", "40")]
    subscription = FakeSubscription(
        soccer_mode="manual",
        soccer_followed_teams=[{"provider": "espn", "team_id": "10"}],
    )

    with patch(
        "teamarr.database.subscription.get_subscription", return_value=subscription
    ):
        kept, count = processor._filter_by_followed_soccer_teams(
            matches, FakeGroup(), SimpleNamespace()
        )

    assert kept == matches
    assert count == 0
