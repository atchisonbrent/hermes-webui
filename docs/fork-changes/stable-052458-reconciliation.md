# Stable 0.52.458 reconciliation

Classification: local-product-delta.

Upstream base: `fd0141fa196fe832171c9c0551bbb8205b6412d4` (`v0.52.458`).
Fork base: `9d8ed352252b863a283202ad1e6f02cd81d006df`.
Maintenance owner: deployment-fork maintainer. This is release reconciliation,
not a new upstream contribution. Reclassification trigger: upstream covers the
remaining fork contracts through supported interfaces.
Rollback: retain the previous paired code/runtime and verified state recovery
set; assess migrations and stop writers before any state replacement.
Private operational details are excluded from this source record.

Merge upstream `v0.52.458` while retaining the deployment fork's profile isolation, config-reference preservation, supervised restart admission, history commentary, display-only input receipts, content-addressed assets and bounded transcript rendering. This is a coupled Agent 0.22.2 compatibility migration, not a replacement with upstream alone.

## Reconciliation decisions

- Prefer upstream presentation over reproducing the old fork layout. Remove the
  nested compact-update disclosure implementation and restore upstream's visible
  prose classification and worklog row renderer. Retain only an additive public-
  commentary adapter in the native step renderer, plus existing recorded-input
  data handling; neither decodes raw replay data or changes stored conversations.
  Obsolete nested-control browser fixtures are replaced by native-layout checks.
  DOM node retention is not a native presentation contract; data preservation is.
- Retain upstream's count-only, writer-vouched `_prefix_message_count` probe and per-version memo. Legacy unmarked sidecars return unknown during SSE reconnect instead of triggering a full transcript parse or a guessed reload. Ordinary session loading preserves their messages; a subsequent normal save publishes a vouched count. This deliberately supersedes the older legacy-count fallback assertion.
- Keep upstream Stop/Steer admission and stream-lock ordering together with the fork's restart drain and display receipts. Queue lookup remains before admission; accepted receipt fields are additive and do not replace the ownership/phase assertions.
- Preserve separately keyed commentary from distinct assistant messages, even when their text is equal. Text-only saved-scene reconciliation must not discard message/part identities. Existing equal-text, joined-commentary and incomplete-trace tests cover this boundary.
- Preserve upstream explicit provider and model resolution alongside fork provider-context rules. Configuration saves still refuse an incompatible Agent rather than materialize environment references.
- Preserve upstream browser recovery and active-window helpers. Focused JavaScript harnesses now load the actual added dependencies; incidental receipt-adoption effects remain stubbed only in the unread-marker test, which does not exercise receipts.

## Supervisor protocol

Drain markers may include the exact `server_started_at` value from health. A valid marker for another generation is ignored; legacy or malformed markers remain fail-closed. Server startup removes only its own PID marker before starting background delivery or reattaching runs, covering same-PID exec. Supervisors must still retire their exact marker after the old worker is gone.

Health exposes the serving PID, `restart_draining`, and separate pending-work counters (deferred entries, retry records, completion markers, wakeup threads, delegation admissions), without session identifiers or prompt text. Counts can overlap; all must be zero for a proven quiet queue. The queue is still in-memory: this does not add persistence or guarantee zero-loss handoff. Older serving versions lack these diagnostics; absence is not proof of an empty queue. Reconcile outstanding work separately before upgrading a legacy server, and avoid in-app update/shutdown paths during supervised cutover.

A reattach worker refused by drain retires only its own active-run claim token; it must never leave a false-busy row or remove a successor's claim.

Real-entrypoint startup and source-level regression checks are qualification evidence, not proof of live authenticated browser or model chat behavior. Deployment requires separate consumer-complete, idle-gated activation and post-restart verification. Keep the stale-Agent runtime guard enabled.
