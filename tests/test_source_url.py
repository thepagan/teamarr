"""Tests for the AGPL source offer URL."""

from teamarr.config import SOURCE_REPOSITORY, get_source_url


def test_source_url_uses_configured_location(monkeypatch) -> None:
    monkeypatch.setenv("TEAMARR_SOURCE_URL", "https://example.com/teamarr-source")
    monkeypatch.setenv("GIT_SHA", "abc123")

    assert get_source_url() == "https://example.com/teamarr-source"


def test_source_url_uses_build_commit(monkeypatch) -> None:
    monkeypatch.delenv("TEAMARR_SOURCE_URL", raising=False)
    monkeypatch.setenv("GIT_SHA", "abc123")

    assert get_source_url() == f"{SOURCE_REPOSITORY}/tree/abc123"


def test_source_url_falls_back_to_project_repository(monkeypatch) -> None:
    monkeypatch.delenv("TEAMARR_SOURCE_URL", raising=False)
    monkeypatch.setenv("GIT_SHA", "unknown")

    assert get_source_url() == SOURCE_REPOSITORY
