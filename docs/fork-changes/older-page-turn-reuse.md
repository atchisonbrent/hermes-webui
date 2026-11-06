# Older-page compact-history reuse

Loading older messages may reuse completed compact assistant turns instead of
reconstructing their tool/thinking DOM on each page. Loaded transcript text stays
in the document; this does not enable virtualization, truncate history or change
auto-load preferences.

The existing settled-turn signature remains the eligibility gate. Pagination
compares the same absolute turn position, message content, preceding boundary,
linked tool results, presentation settings and tool metadata. Window-relative
metadata is normalized for comparison. Reused DOM indices and generated fork/jump
handlers are rebased before the new prefix is rendered. Prior derived metadata is
carried only for comparison; the renderer still reconstructs current tool data.

Live turns, incomplete head/tail boundaries, ambiguous metadata, changed turns,
compression/handoff UI, virtualized rendering and Transparent Stream keep the
ordinary renderer path. This is an optimization of the non-virtualized compact
path, not a new renderer or a guarantee of bounded DOM size.

## Verification

Run with the repository browser-test interpreter and installed Chromium/WebKit:

```
python tests/browser_older_turn_reuse.py
SHAPE=legacy python tests/browser_older_turn_reuse.py
python tests/browser_active_turn_page_boundary.py
```

The pagination test exercises actual `loadSession`, the older-page API path and
renderer with synthetic transport, verifies retained DOM identity and reading
position, disclosure state, searchable prose, shifted message actions and edit
invalidation, and drives the manual button and upward-wheel auto-load. It does not
send a provider request or mutate production session state. Running it on the
pre-change revision fails because the old turn is detached.

Performance must also be measured on representative long tool-heavy history.
Retaining DOM avoids repeated construction but does not eliminate full-history
scans, layout cost, or memory growth. Mobile viewport tests are not physical iOS
acceptance. Baseline suite failures must be reported separately, not silently
reclassified as passing tests.
