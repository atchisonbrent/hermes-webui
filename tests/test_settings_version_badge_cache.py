"""GET /api/settings memoizes the git-derived channel version badge briefly.

``channel_version_badge`` runs two to four git subprocesses per call, and
/api/settings is awaited on page load before the session list is requested.
"""

from pathlib import Path

import pytest

import api.updates as updates

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clear_badge_cache():
    updates._CHANNEL_VERSION_BADGE_CACHE.clear()
    yield
    updates._CHANNEL_VERSION_BADGE_CACHE.clear()


def _count_badge_calls(monkeypatch) -> list:
    calls = []

    def fake_badge(channel=None):
        calls.append(channel)
        return f"v1.2.3-{channel}-{len(calls)}"

    monkeypatch.setattr(updates, "channel_version_badge", fake_badge)
    return calls


def test_badge_is_computed_once_within_ttl(monkeypatch):
    calls = _count_badge_calls(monkeypatch)

    first = updates.cached_channel_version_badge("stable")
    second = updates.cached_channel_version_badge("stable")

    assert first == second == "v1.2.3-stable-1"
    assert calls == ["stable"]


def test_badge_cache_is_keyed_by_channel(monkeypatch):
    calls = _count_badge_calls(monkeypatch)

    assert updates.cached_channel_version_badge("stable") == "v1.2.3-stable-1"
    assert updates.cached_channel_version_badge("experimental") == "v1.2.3-experimental-2"
    assert calls == ["stable", "experimental"]


def test_badge_is_recomputed_after_ttl(monkeypatch):
    calls = _count_badge_calls(monkeypatch)
    now = [1000.0]
    monkeypatch.setattr(updates.time, "monotonic", lambda: now[0])

    updates.cached_channel_version_badge("stable")
    now[0] += updates._CHANNEL_VERSION_BADGE_TTL_SECONDS - 1
    updates.cached_channel_version_badge("stable")
    assert len(calls) == 1
    now[0] += 2
    assert updates.cached_channel_version_badge("stable") == "v1.2.3-stable-2"
    assert len(calls) == 2


def test_badge_cache_is_keyed_by_checkout(monkeypatch, tmp_path):
    calls = _count_badge_calls(monkeypatch)

    updates.cached_channel_version_badge("stable")
    monkeypatch.setattr(updates, "REPO_ROOT", tmp_path)
    updates.cached_channel_version_badge("stable")

    assert len(calls) == 2


def test_settings_route_uses_cached_badge():
    routes_src = (REPO / "api" / "routes.py").read_text(encoding="utf-8")
    start = routes_src.index('if parsed.path == "/api/settings":')
    end = routes_src.index("return j(handler, settings)", start)
    block = routes_src[start:end]

    assert "cached_channel_version_badge(channel)" in block
    assert "= channel_version_badge(" not in block
