#!/usr/bin/env python3
"""Real-browser check of the saved-conversation restore on page load.

Boots the real server.py agent-free on synthetic state, seeds a saved session in
localStorage, routes only that session's /api/session reads to a fixture (no
agent is available to create messages), and asserts that the page:

* restores the saved conversation with no console errors;
* fetches its metadata (messages=0&resolve_model=0) once, not twice;
* starts /api/profile/active before /api/settings has finished;
* starts the saved-session metadata before /api/sessions has finished.

Run: python tests/browser_boot_restore_overlap.py (needs playwright + chromium).
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_conversation_lifecycle import _start_webui_server, _terminate_process  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SID = "abcdef123456"
BENIGN = ("favicon", "manifest.json", "serviceworker", "sw.js",
          "the server responded with a status of 404")
INIT = f"""
if(window===window.top && 'serviceWorker' in navigator){{
  navigator.serviceWorker.register=()=>Promise.reject(new Error('Disabled in restore harness'));
}}
try{{ localStorage.setItem('hermes-webui-session', '{SID}'); }}catch(_){{}}
"""


def _fixture_session(workspace):
    now = time.time()
    return dict(
        session_id=SID, title="Restore fixture", workspace=workspace, model="test-model",
        message_count=2, created_at=now - 60, updated_at=now - 30, last_message_at=now - 30,
        tool_calls=[], active_stream_id=None, pending_user_message=None, archived=False,
        messages=[
            dict(role="user", content="fixture question", timestamp=now - 60),
            dict(role="assistant", content="fixture answer", timestamp=now - 30),
        ],
    )


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright not installed", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="webui-boot-restore-") as temp:
        state = Path(temp)
        env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TMPDIR") if k in os.environ}
        env.update(HOME=temp, HERMES_HOME=temp, HERMES_BASE_HOME=temp,
                   HERMES_WEBUI_STATE_DIR=str(state / "webui"), HERMES_CONFIG_PATH=str(state / "config.yaml"),
                   HERMES_WEBUI_HOST="127.0.0.1", HERMES_WEBUI_SKIP_ONBOARDING="1",
                   HERMES_WEBUI_AGENT_DIR=str(state / "no-agent"))
        if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            env["PLAYWRIGHT_BROWSERS_PATH"] = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
        proc, log, log_path, base = _start_webui_server(ROOT, env, state)
        session = _fixture_session(temp)
        timeline = []
        errors = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                page = browser.new_context(base_url=base).new_page()
                page.add_init_script(INIT)
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("request", lambda r: timeline.append(("start", r.url, time.monotonic())))
                page.on("requestfinished", lambda r: timeline.append(("end", r.url, time.monotonic())))

                def session_route(route):
                    requested = parse_qs(urlsplit(route.request.url).query).get("session_id", [""])[0]
                    if requested != SID:
                        return route.continue_()
                    route.fulfill(json={"session": session})

                page.route("**/api/session?*", session_route)
                page.goto("/", wait_until="domcontentloaded")
                page.wait_for_function("() => typeof S !== 'undefined' && S._bootReady === true", timeout=20000)
                page.wait_for_function(f"() => S.session && S.session.session_id === '{SID}'", timeout=10000)
                time.sleep(0.5)
                browser.close()
        finally:
            _terminate_process(proc)
            log.close()

        def first(kind, needle):
            return next((t for k, u, t in timeline if k == kind and needle in urlsplit(u).path + "?" + urlsplit(u).query), None)

        failures = []
        meaningful = [e for e in errors if not any(b in e.lower() for b in BENIGN)]
        if meaningful:
            failures.append(f"console errors: {meaningful[:3]}")
        metadata = [u for k, u, _ in timeline if k == "start" and f"session_id={SID}" in u
                    and "messages=0" in u and "resolve_model=0" in u]
        if len(metadata) != 1:
            failures.append(f"saved-session metadata fetched {len(metadata)} times, expected 1")
        profile_start, settings_end = first("start", "/api/profile/active"), first("end", "/api/settings")
        if profile_start is None or settings_end is None or not profile_start < settings_end:
            failures.append("/api/profile/active did not start before /api/settings finished")
        meta_start, sessions_end = first("start", f"session_id={SID}&messages=0"), first("end", "/api/sessions?")
        if meta_start is None or sessions_end is None or not meta_start < sessions_end:
            failures.append("saved-session metadata did not start before /api/sessions finished")
        if failures:
            print("BOOT RESTORE OVERLAP FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
            return 1
        print("BOOT RESTORE OVERLAP PASSED — restored with one metadata read and overlapped boot requests")
        return 0


if __name__ == "__main__":
    sys.exit(main())
