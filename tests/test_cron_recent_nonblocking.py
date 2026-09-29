"""Recent-completion requests must not wait for a running cron's env lock."""
import sys
import threading
import types
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlparse


def test_recent_completions_read_own_profile_while_job_holds_env_lock(monkeypatch, tmp_path):
    from api import profiles, routes

    store = ContextVar("test_cron_store", default=None)
    home = tmp_path / "reader"
    foreign = tmp_path / "runner"
    jobs = types.ModuleType("cron.jobs")

    @contextmanager
    def use_cron_store(value):
        token = store.set(Path(value))
        try:
            yield
        finally:
            store.reset(token)

    jobs.use_cron_store = use_cron_store
    jobs.list_jobs = lambda **kw: [{"id": "own" if store.get() == home else "foreign", "last_run_at": "2026-01-01T00:00:00+00:00"}]
    pkg = types.ModuleType("cron")
    pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "cron", pkg)
    monkeypatch.setitem(sys.modules, "cron.jobs", jobs)
    monkeypatch.setattr(profiles, "get_active_hermes_home", lambda: home)
    monkeypatch.setattr(routes, "_ensure_agent_cron_import_path", lambda: None)
    monkeypatch.setattr(routes, "_latest_cron_session_info_for_jobs", lambda *args: {})
    monkeypatch.setattr(routes, "j", lambda handler, data, **kw: data)
    # Compile the actual dispatcher branch, not a replacement implementation.
    source = (Path(routes.__file__)).read_text()
    start = source.index('    if parsed.path == "/api/crons/recent":')
    end = source.index('    if parsed.path == "/api/crons/status":', start)
    namespace = vars(routes).copy()
    exec("def dispatch(handler, parsed):\n" + source[start:end], namespace)
    result = []
    done = threading.Event()

    def read():
        try:
            result.append(namespace["dispatch"](None, urlparse("/api/crons/recent?since=0")))
            result.append(store.get())
        finally:
            done.set()

    # This is the same lock the production run wrapper holds for its lifetime.
    with profiles._cron_env_lock:
        monkeypatch.setenv("HERMES_HOME", str(foreign))
        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        completed_while_locked = done.wait(1)
    thread.join(3)
    assert completed_while_locked, "recent poll waited for the execution lock"
    assert result[0]["completions"][0]["job_id"] == "own"
    assert result[1] is None


def test_legacy_reader_fails_fast_and_releases_after_error(monkeypatch, tmp_path):
    import os
    import pytest
    from api import profiles

    pkg = types.ModuleType("cron")
    pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "cron", pkg)
    monkeypatch.setitem(sys.modules, "cron.jobs", types.ModuleType("cron.jobs"))
    monkeypatch.setitem(sys.modules, "cron.scheduler", types.ModuleType("cron.scheduler"))
    home = tmp_path / "legacy"
    monkeypatch.setattr(profiles, "get_active_hermes_home", lambda: home)
    before = os.environ.get("HERMES_HOME")
    with profiles._cron_env_lock:
        with pytest.raises(TimeoutError):
            with profiles.cron_read_profile_context():
                pytest.fail("must not enter a foreign execution context")
    assert os.environ.get("HERMES_HOME") == before
    assert profiles._cron_profile_context_depth() == 0
    with pytest.raises(ValueError):
        with profiles.cron_read_profile_context():
            assert os.environ["HERMES_HOME"] == str(home)
            raise ValueError("consumer failed")
    assert os.environ.get("HERMES_HOME") == before
    assert profiles._cron_profile_context_depth() == 0
    assert profiles._cron_env_lock.acquire(blocking=False)
    profiles._cron_env_lock.release()


def test_native_store_reads_real_profile_files_without_global_mutation(monkeypatch, tmp_path):
    import json
    import os
    import pytest
    from api import profiles, routes

    routes._ensure_agent_cron_import_path()
    jobs = pytest.importorskip("cron.jobs")
    if not hasattr(jobs, "use_cron_store"):
        pytest.skip("companion agent lacks context-local cron storage")
    home = tmp_path / "reader"
    foreign = tmp_path / "runner"
    for directory, name in ((home, "own"), (foreign, "foreign")):
        (directory / "cron").mkdir(parents=True)
        (directory / "cron/jobs.json").write_text(json.dumps({"jobs": [{"id": name, "name": name}]}))
    monkeypatch.setattr(profiles, "get_active_hermes_home", lambda: home)
    monkeypatch.setenv("HERMES_HOME", str(foreign))
    monkeypatch.setattr(jobs, "JOBS_FILE", foreign / "cron/jobs.json")
    with profiles._cron_env_lock:
        with profiles.cron_read_profile_context():
            assert [job["id"] for job in jobs.list_jobs(include_disabled=True)] == ["own"]
            assert os.environ["HERMES_HOME"] == str(foreign)
            assert jobs.JOBS_FILE == foreign / "cron/jobs.json"
    assert jobs._cron_store_override.get() is None
    with pytest.raises(ValueError):
        with profiles.cron_read_profile_context():
            raise ValueError("reader failure")
    assert jobs._cron_store_override.get() is None
    assert os.environ["HERMES_HOME"] == str(foreign)


def test_dispatch_maps_only_legacy_lock_contention(monkeypatch, tmp_path):
    import pytest
    from api import profiles, routes

    pkg = types.ModuleType("cron")
    pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "cron", pkg)
    monkeypatch.setitem(sys.modules, "cron.jobs", types.ModuleType("cron.jobs"))
    monkeypatch.setitem(sys.modules, "cron.scheduler", types.ModuleType("cron.scheduler"))
    monkeypatch.setattr(profiles, "get_active_hermes_home", lambda: tmp_path)
    source = Path(routes.__file__).read_text()
    start = source.index('    if parsed.path == "/api/crons/recent":')
    end = source.index('    if parsed.path == "/api/crons/status":', start)
    def handler(*args):
        raise TimeoutError("consumer timeout")
    namespace = dict(vars(routes), _ensure_agent_cron_import_path=lambda: None,
                     _handle_cron_recent=handler,
                     j=lambda handler, body, status=200: (status, body))
    exec("def dispatch(handler, parsed):\n" + source[start:end], namespace)
    with profiles._cron_env_lock:
        assert namespace["dispatch"](None, urlparse("/api/crons/recent")) == (503, {"error": "Cron profile is busy"})
    with pytest.raises(TimeoutError, match="consumer timeout"):
        namespace["dispatch"](None, urlparse("/api/crons/recent"))
