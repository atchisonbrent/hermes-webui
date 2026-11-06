from __future__ import annotations

import json
import os
import queue

import pytest


def _clear_run(config, stream_id: str) -> None:
    with config.ACTIVE_RUNS_LOCK:
        config.ACTIVE_RUNS.pop(stream_id, None)


def test_health_exposes_drain_identity_and_pending_work(monkeypatch, tmp_path):
    from api import config, routes
    monkeypatch.setenv('HERMES_WEBUI_RESTART_DRAIN_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'DEFERRED_PROCESS_WAKEUPS', {'private-session': [{}, {}]})
    monkeypatch.setattr(config, 'PENDING_BG_TASK_COMPLETIONS', {'private-session'})
    monkeypatch.setattr(routes, '_DEFERRED_WAKEUP_RETRY_TIMERS', {'private-session': object()})
    payload = routes._run_lifecycle_health()
    assert payload['pid'] == os.getpid()
    assert payload['restart_draining'] is False
    assert payload['pending_wakeups']['deferred_entries'] == 2
    assert payload['pending_wakeups']['retry_records'] == 1
    assert payload['pending_wakeups']['completion_markers'] == 1
    assert 'private-session' not in json.dumps(payload)


def test_generation_bound_marker_and_startup_cleanup(monkeypatch, tmp_path):
    from api import config
    monkeypatch.setenv('HERMES_WEBUI_RESTART_DRAIN_DIR', str(tmp_path))
    marker = tmp_path / f'{os.getpid()}.json'
    marker.write_text(json.dumps({'server_started_at': config.SERVER_START_TIME - 1}))
    assert config.restart_drain_active() is False
    marker.write_text(json.dumps({'server_started_at': config.SERVER_START_TIME}))
    assert config.restart_drain_active() is True
    config.clear_startup_restart_drain()
    assert not marker.exists()
    assert config.restart_drain_active() is False


def test_current_process_drain_marker_refuses_new_run(monkeypatch, tmp_path):
    from api import config

    monkeypatch.setenv("HERMES_WEBUI_RESTART_DRAIN_DIR", str(tmp_path))
    marker = tmp_path / f"{os.getpid()}.json"
    marker.write_text(json.dumps({"reason": "revision_change"}) + "\n")
    stream_id = "drain-current-process"

    with pytest.raises(config.RunAdmissionDrainingError):
        config.register_active_run(stream_id, session_id="session-1")

    with config.ACTIVE_RUNS_LOCK:
        assert stream_id not in config.ACTIVE_RUNS


@pytest.mark.parametrize('lock_held', [False, True])
def test_drain_refuses_new_launch_claim(monkeypatch, tmp_path, lock_held):
    from api import config

    monkeypatch.setenv('HERMES_WEBUI_RESTART_DRAIN_DIR', str(tmp_path))
    (tmp_path / f'{os.getpid()}.json').write_text('{}\n')
    stream_id = 'drain-new-claim'
    try:
        with pytest.raises(config.RunAdmissionDrainingError):
            if lock_held:
                with config.STREAMS_LOCK:
                    config.publish_pre_admission_claim(stream_id, streams_lock_held=True)
            else:
                config.publish_pre_admission_claim(stream_id)
        assert stream_id not in config.PRE_ADMISSION_CLAIMS
    finally:
        config.retire_pre_admission_claim_if_owned(stream_id)


def test_other_process_drain_marker_does_not_refuse_run(monkeypatch, tmp_path):
    from api import config

    monkeypatch.setenv("HERMES_WEBUI_RESTART_DRAIN_DIR", str(tmp_path))
    (tmp_path / f"{os.getpid() + 1}.json").write_text("{}\n")
    stream_id = "drain-other-process"

    try:
        config.register_active_run(stream_id, session_id="session-2")
        with config.ACTIVE_RUNS_LOCK:
            assert config.ACTIVE_RUNS[stream_id]["session_id"] == "session-2"
    finally:
        _clear_run(config, stream_id)


def test_malformed_current_process_marker_still_refuses_run(monkeypatch, tmp_path):
    from api import config

    monkeypatch.setenv("HERMES_WEBUI_RESTART_DRAIN_DIR", str(tmp_path))
    (tmp_path / f"{os.getpid()}.json").write_text("not-json\n")
    stream_id = "drain-malformed-current-process"

    with pytest.raises(config.RunAdmissionDrainingError):
        config.register_active_run(stream_id, session_id="session-3")

    with config.ACTIVE_RUNS_LOCK:
        assert stream_id not in config.ACTIVE_RUNS


def test_chat_start_returns_retryable_maintenance_before_session_mutation(monkeypatch, tmp_path):
    from api import routes

    monkeypatch.setenv("HERMES_WEBUI_RESTART_DRAIN_DIR", str(tmp_path))
    (tmp_path / f"{os.getpid()}.json").write_text("{}\n")
    observed = {}

    def fake_json(_handler, payload, status=200):
        observed.update({"payload": payload, "status": status})
        return True

    monkeypatch.setattr(routes, "j", fake_json)
    monkeypatch.setattr(
        routes,
        "_get_or_materialize_session",
        lambda *_args, **_kwargs: pytest.fail("draining request mutated session state"),
    )

    assert routes._handle_chat_start(object(), {"session_id": "session-4", "message": "hello"}) is True
    assert observed["status"] == 503
    assert observed["payload"]["status"] == "restart_draining"
    assert observed["payload"]["retryable"] is True


def test_server_wakeup_refuses_drain_before_session_mutation(monkeypatch, tmp_path):
    from api import routes

    monkeypatch.setenv('HERMES_WEBUI_RESTART_DRAIN_DIR', str(tmp_path))
    (tmp_path / f'{os.getpid()}.json').write_text('{}\n')
    monkeypatch.setattr(routes, '_agent_runtime_barrier_response', lambda **kwargs: None)
    monkeypatch.setattr(routes, 'get_session', lambda *_: pytest.fail('draining wakeup reached session mutation'))
    result = routes.start_session_turn('session-wakeup', 'completion')
    assert result['_status'] == 503
    assert result['status'] == 'restart_draining'
    assert result['retryable'] is True


def test_local_worker_race_emits_terminal_retryable_event(monkeypatch, tmp_path):
    from api import config, streaming

    monkeypatch.setenv("HERMES_WEBUI_RESTART_DRAIN_DIR", str(tmp_path))
    (tmp_path / f"{os.getpid()}.json").write_text("{}\n")
    stream_id = "drain-worker-race"
    events = queue.Queue()
    with config.STREAMS_LOCK:
        config.STREAMS[stream_id] = events

    try:
        streaming._run_agent_streaming(
            session_id="session-5",
            msg_text="hello",
            model="test-model",
            workspace=str(tmp_path),
            stream_id=stream_id,
        )
        event, payload = events.get_nowait()
        assert event == "apperror"
        assert payload["type"] == "restart_draining"
        assert payload["retryable"] is True
    finally:
        with config.STREAMS_LOCK:
            config.STREAMS.pop(stream_id, None)


def test_gateway_worker_race_emits_terminal_retryable_event(monkeypatch, tmp_path):
    from api import config, gateway_chat

    monkeypatch.setenv("HERMES_WEBUI_RESTART_DRAIN_DIR", str(tmp_path))
    (tmp_path / f"{os.getpid()}.json").write_text("{}\n")
    stream_id = "drain-gateway-worker-race"
    events = queue.Queue()
    with config.STREAMS_LOCK:
        config.STREAMS[stream_id] = events

    try:
        gateway_chat._run_gateway_chat_streaming(
            session_id="session-6",
            msg_text="hello",
            model="test-model",
            workspace=str(tmp_path),
            stream_id=stream_id,
        )
        event, payload = events.get_nowait()
        assert event == "apperror"
        assert payload["type"] == "restart_draining"
        assert payload["retryable"] is True
    finally:
        with config.STREAMS_LOCK:
            config.STREAMS.pop(stream_id, None)


def test_health_advertises_restart_drain_capability(monkeypatch):
    from api import routes

    observed = {}

    def fake_json(_handler, payload, status=200):
        observed.update({"payload": payload, "status": status})
        return True

    monkeypatch.setattr(routes, "j", fake_json)
    parsed = type("Parsed", (), {"query": ""})()

    assert routes._handle_health(object(), parsed) is True
    assert observed["status"] == 200
    assert observed["payload"]["restart_drain_supported"] is True
