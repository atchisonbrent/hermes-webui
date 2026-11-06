# External independent-review sessions

The CLI session bridge can show managed Antigravity reviews alongside native
Claude Code transcripts and Hermes CLI conversations.

- Claude Code uses its native `~/.claude/projects` transcripts. A launcher that
  disables native session persistence will not produce an importable transcript.
- Antigravity uses versioned records under the server's startup `HERMES_HOME`
  (normally `~/.hermes`), at
  `review-sessions/antigravity/<native-conversation-id>.json`.
  `HERMES_WEBUI_ANTIGRAVITY_SESSIONS_DIR` overrides this directory.
- Antigravity records contain the actual submitted task, model identity, last
  recorded status and validated final report. They are **not** a decoder for
  arbitrary Antigravity history databases or a mirror of private reasoning.
- These views are read-only. Opening one does not create a writable Hermes
  conversation, resume the native process, or modify its source records.
  Antigravity projections cannot be publicly shared; no share sidecar is created.
  External identity prefixes stay read-only even when discovery fails.
- Native storage is profile-independent and records appear once in the all-profiles view.
  A named-profile-only filter may hide root-profile external records.
  `show_cli_sessions` is the parent visibility control; the Claude-specific toggle
  continues to affect Claude only.
- Status is the launcher's last recorded state, not a process-liveness guarantee.
  A process killed without cleanup can leave a `started` record.

## Record contract

Version `1` includes `source: "antigravity"`, a canonical UUID in
`native_conversation_id`, `model`, `role`, `workspace`, `status`, numeric
`created_at`/`updated_at` in Unix seconds, and `messages` containing user/assistant text. The
filename must agree with the native UUID. Producers replace records atomically;
WebUI reads them without writing them back. Legacy native-ID sidecars cannot
make public payloads resumable; import refresh stays in memory. POSTs naming
native identities in JSON, query strings, or upload form fields default to denial,
except read-only import and the existing Claude share operations. Whitespace and
case aliases are rejected, not repaired; sidecar loaders require exact stored IDs.
File-view workspace recovery is in memory for native identities.
Single-session deletion is denied even when native discovery is unavailable.
Existing bulk empty-session cleanup and project deletion retain their historical
behavior for legacy WebUI metadata sidecars; these explicitly invoked operations
may delete or update that metadata, but do not modify native transcript records.
Existing sidecar self-healing on reads also remains in place. These are metadata
exceptions, not permission to resume or send messages to native conversations. The composer is read-only
and send is disabled; ordinary chats regain their normal controls without losing
drafts. Existing Claude public
sharing is unchanged; Antigravity projections cannot be shared.

`workspace` is producer provenance, often the frozen receipt workspace rather
than the original authoring checkout. The detail view exposes that value; the
import-view response may retain the active WebUI workspace. Neither is proof of
the original source checkout, and filesystem access still passes the existing
trusted-workspace guard.

Discovery parses the latest 200 native records after a metadata scan. Antigravity
has its own 20-row sidebar window and cannot evict the existing 20-row ordinary
CLI window. Older records remain addressable
by their native session ID. Metadata-only stat-keyed caching avoids retaining
large reports in memory. Operator-selected root aliases are resolved; record
symlinks are still refused.

The reader rejects record symlinks, non-regular files, malformed identities and records
larger than 10 MiB. That is a WebUI input-safety bound, not a review time, finding
or source-exploration limit. Test state disables real-home discovery unless an
explicit fixture directory is supplied.

Verification: `tests/test_antigravity_sessions.py` covers native identity,
read-only import, updates, profile deduplication and hostile filesystem inputs.
The existing Claude Code bridge tests remain applicable.
