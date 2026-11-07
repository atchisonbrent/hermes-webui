"""Page-load session list: serve the last cached list, then wait for its rebuild.

A page load's first ``/api/sessions`` request passes ``allow_stale=1`` so a
source-changed cache entry is served immediately (marked ``stale``) while one
background rebuild refreshes it; the browser's follow-up passes
``wait_rebuild=1`` and waits for that rebuild instead of taking the short stale
wait. Requests without the flags keep the synchronous source-change rebuild.
"""

import threading
import time
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

import api.routes as routes


@pytest.fixture(autouse=True)
def _isolated_session_list_cache_state():
    routes._session_list_cache_clear()
    with routes._SESSIONS_CACHE_LOCK:
        routes._SESSIONS_CACHE_INFLIGHT.clear()
    yield
    routes._session_list_cache_clear()
    with routes._SESSIONS_CACHE_LOCK:
        routes._SESSIONS_CACHE_INFLIGHT.clear()


def _payload(marker: str) -> dict:
    return {
        "sessions": [{"session_id": marker}],
        "cli_count": 0,
        "all_profiles": False,
        "active_profile": None,
        "other_profile_count": 0,
    }


def _source_changed_key(monkeypatch) -> tuple:
    key = routes._session_list_cache_key(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
    )
    routes._session_list_cache_set(key, _payload("stale"))
    # A source stamp that no longer matches the cached entry: committed state
    # changed after the list was cached (the page-load-after-idle case).
    monkeypatch.setattr(routes, "_session_list_cache_source_stamp", lambda _key: ("changed",))
    return key


def _wait_for_cached(key, marker: str) -> dict | None:
    for _ in range(40):
        cached, _fresh = routes._session_list_cache_get(key, allow_stale=True)
        if cached == _payload(marker):
            return cached
        time.sleep(0.05)
    return None


def test_allow_stale_serves_source_changed_entry_and_rebuilds_in_background(monkeypatch):
    key = _source_changed_key(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def builder():
        started.set()
        release.wait(5)
        return _payload("fresh")

    freshness = {}
    try:
        began = time.monotonic()
        result = routes._get_cached_session_list_payload(
            key=key, builder=builder, serve_source_stale=True, freshness=freshness,
        )
        assert time.monotonic() - began < 1.0, "page load must not wait for the rebuild"
        assert result == _payload("stale")
        assert freshness == {"source_stale": True}
        assert started.wait(1.0), "serving stale must start a background rebuild"
    finally:
        release.set()
    assert _wait_for_cached(key, "fresh") is not None


def test_without_allow_stale_source_change_still_rebuilds_synchronously(monkeypatch):
    key = _source_changed_key(monkeypatch)
    freshness = {}

    result = routes._get_cached_session_list_payload(
        key=key, builder=lambda: _payload("fresh"), freshness=freshness,
    )

    assert result == _payload("fresh")
    assert freshness == {}


def test_age_only_stale_entry_is_not_marked(monkeypatch):
    monkeypatch.setattr(routes, "_session_list_cache_source_stamp", lambda _key: ("stable",))
    key = routes._session_list_cache_key(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
    )
    routes._session_list_cache_set(key, _payload("aged"))
    with routes._SESSIONS_CACHE_LOCK:
        ts, stamp, payload = routes._SESSIONS_CACHE[key]
        routes._SESSIONS_CACHE[key] = (ts - routes._SESSIONS_CACHE_TTL_SECONDS - 1.0, stamp, payload)
    freshness = {}

    result = routes._get_cached_session_list_payload(
        key=key, builder=lambda: _payload("rebuilt"), serve_source_stale=True, freshness=freshness,
    )

    assert result == _payload("aged")
    assert freshness == {}, "an entry whose sources are unchanged has current content"
    assert _wait_for_cached(key, "rebuilt") is not None


def test_wait_rebuild_follow_up_waits_for_in_flight_rebuild(monkeypatch):
    key = _source_changed_key(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def builder():
        started.set()
        release.wait(5)
        return _payload("fresh")

    routes._get_cached_session_list_payload(key=key, builder=builder, serve_source_stale=True)
    assert started.wait(1.0)

    result = {}
    freshness = {}

    def follow_up():
        result["payload"] = routes._get_cached_session_list_payload(
            key=key,
            builder=lambda: pytest.fail("the follow-up must not start a second rebuild"),
            await_rebuild=True,
            freshness=freshness,
        )

    thread = threading.Thread(target=follow_up)
    thread.start()
    # Well past the 0.10 s stale wait a plain follower would have used.
    time.sleep(routes._SESSIONS_CACHE_STALE_WAIT_SECONDS * 4)
    assert thread.is_alive(), "wait_rebuild must keep waiting for the in-flight rebuild"
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert result["payload"] == _payload("fresh")
    assert freshness == {}


def test_plain_follower_during_rebuild_gets_marked_stale(monkeypatch):
    key = _source_changed_key(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def builder():
        started.set()
        release.wait(5)
        return _payload("fresh")

    try:
        routes._get_cached_session_list_payload(key=key, builder=builder, serve_source_stale=True)
        assert started.wait(1.0)
        freshness = {}
        result = routes._get_cached_session_list_payload(
            key=key, builder=builder, freshness=freshness,
        )
        assert result == _payload("stale")
        assert freshness == {"source_stale": True}, "the browser needs the flag to follow up"
    finally:
        release.set()
    # Let the background rebuild finish before the fixture clears the cache.
    assert _wait_for_cached(key, "fresh") is not None


def test_sessions_route_passes_flags_and_marks_stale_response(monkeypatch):
    calls = []

    def fake_cached_payload(**kwargs):
        calls.append(kwargs)
        kwargs["freshness"]["source_stale"] = True
        return _payload("stale")

    captured = {}
    monkeypatch.setattr(routes, "_get_cached_session_list_payload", fake_cached_payload)
    monkeypatch.setattr(routes, "load_settings", lambda: {"api_redact_enabled": False})
    monkeypatch.setattr("api.profiles.get_active_profile_name", lambda: "default")
    monkeypatch.setattr(
        routes, "j", lambda handler, payload, status=200, **_kw: captured.update(payload=payload, status=status),
    )

    routes.handle_get(
        SimpleNamespace(),
        urlparse("/api/sessions?sidebar_source=webui&exclude_hidden=1&allow_stale=1"),
    )

    assert calls[0]["serve_source_stale"] is True
    assert calls[0]["await_rebuild"] is False
    assert captured["status"] == 200
    assert captured["payload"]["stale"] is True

    calls.clear()
    monkeypatch.setattr(
        routes,
        "_get_cached_session_list_payload",
        lambda **kwargs: calls.append(kwargs) or _payload("fresh"),
    )
    routes.handle_get(SimpleNamespace(), urlparse("/api/sessions?sidebar_source=webui&wait_rebuild=1"))

    assert calls[0]["serve_source_stale"] is False
    assert calls[0]["await_rebuild"] is True
    assert "stale" not in captured["payload"]
