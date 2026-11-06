# Persisted recovery counts

The per-session SSE subscribe recovery check reads the persisted sidecar metadata directly, rather than a resident Session object. Its comparison uses the same persisted message-count basis as the loaded snapshot. A stale high count must not trigger a reload loop; a stale low count must not hide a completed turn. Active session owners, transcript contents and persistence writes are unchanged. Modern sidecars use the bounded metadata reader; legacy files may require a full sidecar read on a facts-cache miss and still consult the index on each lookup. Missing or unreadable counts remain unknown, not a reload trigger.

## Verification

`tests/test_session_recovery_persisted_count.py` contains isolated regression coverage. Tests use temporary sidecars and resident cache entries to check the real persisted reader and recovery decision. They do not simulate cross-process writes during a read.

## Compatibility and rollback

This change is independent of the other long-chat fixes and introduces no dependencies or configuration. Revert this commit to remove it; no state migration is needed. Backend changes require a normal service restart.
