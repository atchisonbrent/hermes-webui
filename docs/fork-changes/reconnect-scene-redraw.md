# Avoid quadratic live-scene reconstruction on reconnect

## Upstream candidate

- **Classification:** upstream-candidate; no installation-specific runtime behavior.
- **Upstream base:** `nesquena/hermes-webui` `master`, recorded upstream ref
  `e168b67e4278df618d1cab61fdb3a8dc55b29a81`.
- **Tested fork baseline:** `5a79ced72113544064789e6aa2ddc2750feaa426`.
- **Problem:** opening an active session with a large tool history blocks the
  browser main thread. Users can encounter unresponsive-page warnings or mobile
  reloads before the conversation becomes usable.
- **Expected behavior:** restore the complete live activity scene with a bounded
  number of scene renders, retaining all tools and continuing live updates.
- **Actual behavior:** after a successful scene restore, `loadSession` replays
  each saved tool through `appendLiveToolCard`. When the scene owns the DOM,
  each call redraws the entire scene rather than incrementally adding a card.
- **Root cause:** N saved tools cause N additional full-scene renders; with N
  scene rows the reconnect replay does quadratic row-render work.
- **Change:** return from the per-tool replay helper when `restoredAnchorScene`
  is truthy. That flag records a successful render, not merely snapshot presence.
  Failed scene restoration and legacy HTML recovery still use the existing
  per-tool replay and unkeyed-duplicate behavior.
- **Compatibility / risk:** JavaScript-only change; no schemas, APIs, settings,
  provider behavior, history limits, or stored tool results change. The guard
  depends on the scene renderer continuing to report success only after it
  has restored the authoritative scene.
- **Maintenance owner:** fork maintainers (Brent Atchison).
- **Rollback:** revert this logical change and reload the frontend. No database
  restoration or migration is necessary.
- **Upstream status:** issue-ready; no upstream issue or PR filed by this change.
- **Private details removed:** yes. Published fixtures are synthetic; optional
  private snapshot input stays outside the repository and is not screenshotted.

## Reproduction and verification

Run the inexpensive regression and adjacent lifecycle tests:

```sh
./scripts/test.sh tests/test_reconnect_scene_redraw.py \
  tests/test_inflight_stream_reuse.py \
  tests/test_stable_assistant_turn_anchor_registry.py \
  tests/test_run_journal_routes.py tests/test_regressions.py -q
```

Recorded result: **173 passed, 1 skipped** (agent-dependent test unavailable in
this isolated environment). The new regression fails on the baseline because
470 keyed tools cause 470 scene redraws; the patched replay helper causes zero.
Tests also preserve keyed replay and the unkeyed legacy/failed-scene fallbacks.

For full-page browser coverage, install Playwright in the test environment and
its Chromium/WebKit browsers, then run:

```sh
.venv/bin/python -m playwright install chromium webkit
.venv/bin/python tests/browser_reconnect_scene_redraw.py
```

The browser harness starts an isolated loopback server with a temporary home
and no provider credentials. It executes production `loadSession`, renderers,
and SSE handlers with deterministic HTTP/EventSource fixtures. Service-worker
registration is disabled so WebKit cannot bypass fixture routing; this is not
an end-to-end PWA-cache or real-provider reconnect test.

All **12 cases** passed: Chromium/WebKit, 1280/390-pixel viewports, and compact,
transparent, or final-answer-only activity modes. Visible modes retain all 470
tools, display subsequent tool completions, and retain those results after
switching away and back. The transport resumes after the snapshot journal
cursor. Final-answer-only mode keeps activity hidden while retaining busy state.
No page errors were observed. Physical iOS memory pressure was not tested.

In a same-host Chromium comparison using the same generated 470-tool fixture,
the baseline took approximately **23.3 seconds / 472 scene renders**, versus
**0.12–0.20 seconds / 2 scene renders** after the patch. These are local fixture
measurements, not a universal latency guarantee. WebKit visible-mode cases took
approximately 0.20–0.37 seconds. Timing is reported, not used as a flaky CI gate;
the regression asserts operation counts and output preservation instead.

Set `WEBUI_TEST_ROOT` to a pristine baseline worktree and `MEASURE_BASELINE=1`
to collect comparative timings without the patched redraw-count assertion.
`BROWSERS`, `MODES`, and `TOOL_COUNT` narrow the matrix. `METRICS_FILE` saves
count/timing results; `SCREENSHOT_DIR` captures only generated fixtures.

## Deployment boundary

The production change is confined to `static/sessions.js`. The existing server
invalidates its static-byte cache when file size/mtime changes, and the existing
service worker fetches shell assets with `cache: no-store`. An asset-only rollout
can therefore take effect on page reload without interrupting active runs.
Browsers without a controlling service worker may require a cache-bypassing
reload until the next normal process restart changes the versioned asset URL.
Do not force a backend restart merely to activate this rendering fix.

Before upstream submission, reconstruct this small change on current upstream
`master` and rerun its tests. Retire the fork delta when upstream contains an
equivalent fix; do not carry duplicate reconnect logic indefinitely.
