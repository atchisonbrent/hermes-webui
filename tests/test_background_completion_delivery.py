"""Process completions belong in current work, not one follow-up per process."""
import pytest

from tests.test_wakeup_defer_race import (
    _FakeProcessRegistry, _completion_evt, _install_fake_registry,
    _install_fake_start_session_turn, _reset_cfg_state, _wait_for_wakeup,
)


@pytest.fixture
def delivery(monkeypatch):
    from api import background_process as bp, config as cfg
    fake = _FakeProcessRegistry()
    _install_fake_registry(monkeypatch, fake)
    _reset_cfg_state()
    holder = _install_fake_start_session_turn(monkeypatch)
    sid = "session-delivery"
    bp.register_process_session(sid, sid)
    cfg.ACTIVE_RUNS["stream-delivery"] = {"session_id": sid}
    yield bp, cfg, fake, holder, sid
    _reset_cfg_state()


def enqueue(delivery, count):
    bp, cfg, fake, holder, sid = delivery
    for i in range(count):
        pid = f"proc-{i}"
        fake.register(pid, sid)
        evt = _completion_evt(pid, sid)
        # Same shape as the reported burst: redirected outputs and unknown exit.
        evt.update(command=f"python check-{i}.py > result-{i}.log", exit_code=None)
        bp._process_one(evt)


@pytest.mark.parametrize('retry_attempt', [0, 1])
def test_known_drain_refusal_preserves_launch_retry_budget(delivery, monkeypatch, retry_attempt):
    from types import SimpleNamespace
    from api import routes
    bp, cfg, fake, holder, sid = delivery
    retries = []
    monkeypatch.setattr(routes, 'start_session_turn', lambda *a, **kw: {
        '_status': 503, 'status': 'restart_draining', 'retryable': True})
    monkeypatch.setattr(routes, '_schedule_deferred_wakeup_retry',
                        lambda sid, **kw: retries.append((sid, kw)))
    monkeypatch.setattr(bp.threading, 'Thread', lambda target, **kw: SimpleNamespace(start=target))
    entries = [{'process_id': 'drain-process', 'wakeup_prompt': 'completed work'}]
    bp._start_server_side_wakeup_turn(sid, '', entries=entries, retry_attempt=retry_attempt)
    assert cfg.DEFERRED_PROCESS_WAKEUPS[sid] == entries
    assert retries == [(sid, {'retry_attempt': retry_attempt, 'refund_attempt': True})]
    assert not fake._completion_consumed


@pytest.mark.parametrize('retry_attempt', [0, 1])
def test_completion_delivered_once_after_fence_outlasts_multiple_timers(delivery, monkeypatch, retry_attempt):
    from types import SimpleNamespace
    from api import routes
    from tests.test_issue7680_wakeup_launch_abort_retry import _FakeTimer
    bp, cfg, fake, holder, sid = delivery
    cfg.unregister_active_run('stream-delivery')
    fake.register('drain-process', sid)
    fenced = [True]
    accepted = []
    def start(*args, **kwargs):
        if fenced[0]:
            return {'_status': 503, 'status': 'restart_draining', 'retryable': True}
        accepted.append(kwargs)
        return {'stream_id': 'delivered'}
    monkeypatch.setattr(routes, 'start_session_turn', start)
    monkeypatch.setattr(bp.threading, 'Thread', lambda target, **kw: SimpleNamespace(start=target))
    _FakeTimer.instances = []
    monkeypatch.setattr(routes.threading, 'Timer', _FakeTimer)
    monkeypatch.setattr(routes, '_DEFERRED_WAKEUP_RETRY_TIMERS', {})
    entries = [{'process_id': 'drain-process', 'wakeup_prompt': 'completed work'}]
    bp._start_server_side_wakeup_turn(sid, '', entries=entries, retry_attempt=retry_attempt)
    for index in range(2):
        timer = _FakeTimer.instances[index]
        assert timer.args == (sid, retry_attempt)
        timer.fn(*timer.args)
        assert not accepted
        assert cfg.DEFERRED_PROCESS_WAKEUPS[sid] == entries
    fenced[0] = False
    timer = _FakeTimer.instances[-1]
    timer.fn(*timer.args)
    assert len(accepted) == 1
    assert sid not in cfg.DEFERRED_PROCESS_WAKEUPS
    assert sid not in routes._DEFERRED_WAKEUP_RETRY_TIMERS
    assert fake.is_completion_consumed('drain-process')


@pytest.mark.parametrize('status,error,terminal', [
    (400, 'Invalid workspace', False), (401, 'Authentication required', False),
    (403, 'Permission denied', False), (404, 'Unknown route', False),
    (404, 'Session not found', True), (500, 'Launch failed', False),
])
def test_only_confirmed_missing_session_discards_completion(delivery, monkeypatch, status, error, terminal):
    from types import SimpleNamespace
    from api import routes
    bp, cfg, fake, holder, sid = delivery
    fake.register('refused-process', sid)
    monkeypatch.setattr(routes, 'start_session_turn', lambda *a, **kw: {'_status': status, 'error': error})
    monkeypatch.setattr(bp.threading, 'Thread', lambda target, **kw: SimpleNamespace(start=target))
    entries = [{'process_id': 'refused-process', 'wakeup_prompt': 'completed work'}]
    bp._start_server_side_wakeup_turn(sid, '', entries=entries)
    assert cfg.DEFERRED_PROCESS_WAKEUPS.get(sid, []) == ([] if terminal else entries)
    assert fake.is_completion_consumed('refused-process') is terminal


@pytest.mark.parametrize('format_error', [False, True])
def test_unformattable_event_does_not_leave_false_work_or_consume_result(delivery, monkeypatch, format_error):
    bp, cfg, fake, holder, sid = delivery
    original = bp.format_wakeup_prompt
    def empty(evt):
        if format_error:
            raise RuntimeError('synthetic formatter error')
        return ''
    monkeypatch.setattr(bp, 'format_wakeup_prompt', empty)
    enqueue(delivery, 1)
    assert sid not in cfg.PENDING_BG_TASK_COMPLETIONS
    assert not fake._completion_consumed
    assert 'proc-0' not in cfg.BG_TASK_COMPLETE_EVENTS_SEEN.get(sid, set())
    monkeypatch.setattr(bp, 'format_wakeup_prompt', original)
    bp._process_one(_completion_evt('proc-0', sid))
    assert cfg.DEFERRED_PROCESS_WAKEUPS[sid][0]['process_id'] == 'proc-0'


@pytest.mark.parametrize('retry_attempt', [0, 1])
def test_batched_launch_abort_preserves_individual_prompts(delivery, monkeypatch, tmp_path, retry_attempt):
    from api import routes
    from tests.test_issue7680_wakeup_launch_abort_retry import _install_launch_abort, _FakeTimer

    bp, cfg, fake, holder, sid = delivery
    session, launch = _install_launch_abort(monkeypatch, sid)
    session.workspace = str(tmp_path)
    failing_thread = routes.threading.Thread

    class DispatchThread:
        def __init__(self, target=None, args=(), kwargs=None, **extra):
            self.target, self.args, self.kwargs = target, args, kwargs or {}
        def start(self):
            if getattr(self.target, '__name__', '') == '_runner':
                assert callable(self.target)
                return self.target(*self.args, **self.kwargs)
            return failing_thread().start()

    monkeypatch.setattr(routes.threading, 'Thread', DispatchThread)
    _FakeTimer.instances = []
    monkeypatch.setattr(routes.threading, 'Timer', _FakeTimer)
    monkeypatch.setattr(routes, '_DEFERRED_WAKEUP_RETRY_TIMERS', {})

    def start(sid, message, **kwargs):
        return routes._start_chat_stream_for_session(
            session, msg=message, workspace=str(tmp_path), model='m', model_provider='p', **kwargs)

    monkeypatch.setattr(routes, 'start_session_turn', start)
    entries = [{'process_id': f'proc-{i}', 'wakeup_prompt': f'completion-{i}'} for i in range(2)]
    for entry in entries:
        fake.register(entry['process_id'], sid)
    cfg.unregister_active_run('stream-delivery')
    bp._start_server_side_wakeup_turn(sid, '', process_id='proc-0', entries=entries, retry_attempt=retry_attempt)
    assert launch['attempts'] == 1
    queued = {entry['process_id']: entry['wakeup_prompt'] for entry in cfg.DEFERRED_PROCESS_WAKEUPS[sid]}
    assert queued == {entry['process_id']: entry['wakeup_prompt'] for entry in entries}
    assert len(_FakeTimer.instances) == (1 if retry_attempt == 0 else 0)
    assert not fake._completion_consumed


def test_eight_pending_completions_make_one_idle_continuation(delivery):
    bp, cfg, fake, holder, sid = delivery
    enqueue(delivery, 8)
    cfg.unregister_active_run("stream-delivery")
    assert bp.drain_deferred_wakeups_for_session(sid) == 1
    assert _wait_for_wakeup(holder)
    prompt = holder["calls"][0]["message"]
    assert all(f"proc-{i}" in prompt for i in range(8))
    assert sid not in cfg.DEFERRED_PROCESS_WAKEUPS
    assert bp.drain_deferred_wakeups_for_session(sid) == 0
    assert len(holder["calls"]) == 1


def test_queued_is_not_consumed_and_read_output_retires_wakeup(delivery):
    bp, cfg, fake, holder, sid = delivery
    enqueue(delivery, 2)
    assert fake._completion_consumed == set()
    # This is what core wait()/read_log() sets after actual output consumption.
    fake._completion_consumed.add("proc-0")
    cfg.unregister_active_run("stream-delivery")
    bp.drain_deferred_wakeups_for_session(sid)
    assert _wait_for_wakeup(holder)
    assert "proc-0" not in holder["calls"][0]["message"]
    assert "proc-1" in holder["calls"][0]["message"]




def test_deferred_event_cannot_be_stolen_by_next_turn_queue(delivery):
    from api import streaming
    bp, cfg, fake, holder, sid = delivery
    enqueue(delivery, 1)
    fake.completion_queue.put(_completion_evt("proc-0", sid))
    assert streaming._drain_webui_process_notifications(sid) == []
    assert not fake.is_completion_consumed("proc-0")
    assert len(cfg.DEFERRED_PROCESS_WAKEUPS[sid]) == 1


def test_batch_admission_race_keeps_every_process(delivery, monkeypatch):
    from tests.test_wakeup_defer_race import _wait_for
    bp, cfg, fake, holder, sid = delivery
    holder = _install_fake_start_session_turn(monkeypatch, status=409)
    enqueue(delivery, 8)
    cfg.unregister_active_run("stream-delivery")
    bp.drain_deferred_wakeups_for_session(sid)
    assert _wait_for_wakeup(holder)
    assert _wait_for(lambda: len(cfg.DEFERRED_PROCESS_WAKEUPS.get(sid, [])) == 8)
    assert {e["process_id"] for e in cfg.DEFERRED_PROCESS_WAKEUPS[sid]} == {f"proc-{i}" for i in range(8)}
