# Settled-turn render reuse

Send and completion can reuse complete unchanged historical assistant turns without detaching their DOM. Reuse is opt-in; ordinary rendering remains the invalidation path. Signatures cover presentation settings, message data and linked tool results. Live/latest turns, ambiguous legacy routing, compression/handoff UI and virtualized windows keep the ordinary path. Collapsed transparent tool details are built when expanded; timestamp formatters are bounded and reused. Prose-only completion avoids a second unnecessary collapse pass. This changes display work only, not retention, model context or persistence.

## Verification

`tests/browser_settled_turn_reuse.py` contains isolated regression coverage. The browser harness uses the real page and renderer with synthetic session/SSE transport, temporary state and no provider calls. It does not establish physical iOS behavior.

## Compatibility and rollback

Reuse is an optimization within a mounted transcript, not a guarantee across session switches. HTML-cache restoration does not retain JavaScript memo properties; the next ordinary render safely rebuilds them. Signatures deliberately compare complete relevant payloads rather than a shallow hash that could miss corrected tool output. Local-day changes invalidate relative timestamps; turns adjacent to process-wakeup rows retain full rendering because reasoning comparisons can cross that boundary.

Run `.venv/bin/python tests/browser_settled_turn_reuse.py` with Playwright Chromium/WebKit installed. This browser harness is manual, not part of hosted CI.

This frontend-only change introduces no dependencies or configuration. Revert this commit to remove it; no state migration is needed. Clients must load the updated JavaScript.
