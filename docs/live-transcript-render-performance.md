# Long-session rendering performance

## Upstream Candidate

Classification: upstream-candidate

Upstream base: `nesquena/hermes-webui` `origin/master` merge-base `fd0141fa196fe832171c9c0551bbb8205b6412d4`. The exact fork deployment baseline is `bd100af59f532fac427f9811782660ba6f6ba27b` (fork PR #2, not an upstream commit). Upstream work through `f65960b46` was inspected; any eventual PR requires fresh upstream reconstruction and requalification rather than replaying fork history.

Problem: opening or reconnecting a very large active conversation can make the browser tab unresponsive on desktop and mobile for tens of seconds. Hundreds of activity bursts and thousands of tool/activity events can keep the UI largely unusable during continued streaming.

Reproduction: use a generic active-run fixture with hundreds of activity bursts, each containing visible prose, shared cumulative reasoning, and hundreds of tool calls. Reconnect to that run with virtualization disabled and with each activity display mode. No production transcript, user identity, infrastructure, or private fixture is included in the claim or tests.

Expected behavior: transcript and activity history remain fully available, preferences stay unchanged, and rendering/cache work scales with distinct content instead of repeatedly processing the same shared strings.

Actual behavior: signature construction and reasoning-echo processing repeatedly hash, sanitize, and normalize one shared multi-megabyte string per burst. Cold cache misses also compute signatures when no comparable cached entry exists or the resulting transcript is ineligible for HTML caching. Baseline measurements showed synchronous main-thread stalls rather than merely slow server work.

Root cause: burst projection shares one reasoning value across every live message segment. `_messageRenderCacheSignature` hashes that value for every segment. Rendering also sanitizes and normalizes it for each burst, and `_worklogReasoningTextFromMessage` compares it against different visible text. The former duplicate cost becomes superlinear as bursts and reasoning grow; the persistent cache gate does redundant work when there is no candidate entry to compare or save against.

Change:
1. Memoize sanitized and normalized echo text only for the duration directly attributable to one `renderMessages` call, with full-string keys and a legacy uncached six-argument fallback. Preserve XML/DSML stripping and echo suppression semantics.
2. Hash each distinct long string once per signature invocation. Later repeats mix a first-occurrence ordinal (`0x10000 + ordinal`) plus separator into the signature so same-length repeat sequences retain identity and order. The map is bounded by the invocation and ordinary 32-bit collision limitations remain unchanged.
3. Look up a comparable cached entry before calculating its signature. Cache-eligible saves compute or reuse the post-render signature as already happened for in-session saves. On a first visit with no comparable cached entry that signature now reflects derived tool calls, which may cost a later cache miss but cannot serve stale content. There is no alternate pre-derive persistence mechanism.

Verification:
- `_messageRenderCacheSignature` rejects stale-content, insertion-order, recursion-depth/cyclic and same-length repeat-sequence collisions. The old repeated-value design is tested explicitly with `[A,B,A]` versus `[A,B,B]` and `[A,B,B,A]` versus `[A,B,A,B]`.
- A character-count harness rejects the old 2.4M-visits case.
- Differential reasoning tests cover empty/exact/whitespace echoes, strict substrings in both directions, final-only and secondary visible-only matches, XML/DSML stripping, and cross-order reuse with absolute expected results.
- 254 focused tests pass on the final revision through `./scripts/test.sh tests/test_reasoning_echo_scaling.py tests/test_issue2613_render_cache_signature.py tests/test_inflight_stream_reuse.py tests/test_live_to_final_anchor_visible_order.py tests/test_issue5637_stale_anchor_guard.py tests/test_issue5367_transparent_live_row_reconcile.py tests/test_issue6999_turn_context_virtual_gap.py tests/test_issue3709_thinking_double_render.py tests/test_ui_tool_call_cleanup.py tests/test_issue3820_chat_activity_display_mode.py -q`, including affected neighboring files with isolated per-process state.
- The real reconnect gate passes 12 cases covering Chromium/WebKit, desktop and 390px, compact/transparent/final-answer modes, tool identity, stream cursor continuity, later completion, and session switching.
- A local active-session browser replay preserves full activity while reducing the dominant synchronous render and long-task time by roughly an order of magnitude. Desktop/narrow-browser observations are not physical-device measurements.
- The broad suite is reported separately when complete; it is not represented here as green until observed. GitHub CI remains an independent required gate, not a substitute for local execution.

Compatibility / risk: no model/reasoning capacity reduction, history truncation, preference migration, backend protocol change, new dependency, new service, or runtime configuration change. Transcript/activity content stays available. Native string hash-map equality cost varies by engine and physical iOS has not been profiled. The existing ordinary 32-bit hash collision boundary is unchanged. The reviewed optional pre-derive cold-save optimization was rejected after review and is intentionally not included.

Maintenance owner: Brent Atchison for the personal deployment; Hermes WebUI maintainers after upstream acceptance. Additional local automation is not required.

Rollback: revert the reviewed commit and redeploy the prior `static/ui.js` asset. No data/schema/service rollback is needed. Preserve all transcript files and running agent work.

Upstream status: issue-ready

Private details removed: yes. The tracked record and tests contain no production session IDs, titles, hostnames, private raw transcript payloads, credentials, or deployment-specific configuration.

Future decision: prepare a current-upstream PR only after reproducing the vulnerable shape there and rerunning the focused checks on that exact current tree. Reclassify or retire the delta if upstream independently covers the same behavior; do not keep an obsolete duplicate patch through repeated rebuilds.
