# Commentary in settled history

Intermediate assistant replies are conversation prose, not reasoning. Compact
**Processed** groups use upstream's prose/thinking/tool rows, without fork-only
nested update disclosures; the final answer remains outside. Transparent Stream displays the same public
commentary inline. Final-answer-only mode continues to hide activity.

The session GET and completion payloads use the agent's optional
`agent.history_commentary.project_history_commentary` API to derive
`display_commentary` and `display_reasoning` in the session's owning profile.
This applies the agent's commentary settings to newly projected text, with think
stripping and redaction. It does not retract public prose already retained in an
older saved activity scene; final-answer-only mode hides that activity as before.
The browser never reconstructs public text from raw `codex_message_items`.
Older agents without that API retain their existing history rendering. Imported
`display_*` fields are discarded and regenerated; optional-helper exceptions or
row-alignment changes cannot break session reads or terminal payload delivery.

Projection changes neither provider replay nor the stored message `content`,
message indices, identities, or canonical transcripts. Existing history can
recover public commentary even when the browser never saved an activity scene.
Saved scenes are supplemented from the projected transcript; no migration,
scene-cache expansion or model request is needed. HTML cache signatures include
the projected fields. Projected scene rows retain their owning message index and
commentary ordinal, so equal updates in separate steps are not globally erased.
Persisted steering inputs do not start a new assistant run; cross-block ownership
requires an indexed scene row or matching tool identities plus all public prose.

Existing text-prefix heuristics for legacy scene rows are not broadened. An
unidentifiable partial saved trace may remain beside recovered complete prose;
this repair prefers retaining that trace over guessing which text to delete.

## Verification

- `./scripts/test.sh tests/test_history_commentary_projection.py tests/test_history_commentary_render.py tests/test_anchor_scene_persistence.py`
- `.venv/bin/python tests/browser_upstream_worklog.py` verifies native controls,
  final-answer visibility, tool rows and a recorded steer across reloads.
- `HERMES_WEBUI_AGENT_DIR=/path/to/qualified/hermes-agent .venv/bin/python tests/browser_history_commentary.py`
- Repeat the real-API browser test with `COMMENTARY_DISABLED=1 KINDS=legacy,scene`
  for the new-projection policy negative control. `saved`/`steer` fixtures also
  contain pre-existing public scene prose, which that setting does not retract.
- `.venv/bin/python tests/browser_user_input_receipts.py` exercises the stream
  entrypoint through done/rerender/reload using deterministic events. Native DOM
  rebuilding is allowed; recorded identities/content, ordering and isolation are not relaxed.
- `ACTIVITY_MODE=hide_all_activity COMMENTARY_ONLY=1 KINDS=legacy` checks that
  commentary-only messages create no empty worklog in final-answer-only mode.
  All browser fixtures use isolated temporary state, not the operator's sessions.

The browser test exercises real session reads, reload, older-page loading and
HTML-cache restoration in Chromium/WebKit at desktop and narrow widths. This is
not physical-device certification or a live-provider inference test.

## Remaining boundaries

GET and stream settlement regenerate display fields; import/workspace/sync response
paths are not newly certified. The optional helper receives a deep copy so even
nested mutations cannot affect canonical history. Helper failure logs use a fixed,
non-sensitive warning; rate-limited diagnostic logging is not part of this repair.
Mixed reasoning carriers, previously saved unstripped thinking rows, and scenes
without tools or thinking retain legacy rendering limitations. This change targets
intermediate public updates in compact history, not a redesign of scene ownership
or all activity modes. Browser fixtures are explicit scripts, not pytest-collected.
Use `CONTENT_STEER=1 KINDS=steer` for the real-API fixture (also with
`COMMENTARY_DISABLED=1`) to cover persisted steering.
Full-transcript settlement projection now deep-copies nested payloads for isolation;
large tool-result transcripts can cost more than windowed GETs. Earlier shallow-copy
microbenchmarks do not certify this bound. Steering fixtures exercise persisted
`display_kind: "steer"` inputs; the producer is agent-owned and outside this WebUI
repository. Live ownership without a message index remains conservative: unsupported
tool-carrier shapes may leave a duplicate rather than hiding unmatched public text.
