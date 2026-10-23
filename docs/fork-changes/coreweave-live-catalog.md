# Named provider live catalogs

Classification: upstream-candidate
Upstream base: origin/master ancestry fd0141fa196fe832171c9c0551bbb8205b6412d4; implementation on reviewed fork baseline bbadbcb1e7f6bd05618a58c2e64cf41bebd981ca.
Problem: a named custom provider can advertise live discovery yet receive native-provider inventory or no inventory; its configured display name is ignored in the picker.
Reproduction: run tests/test_named_provider_catalog.py with a providers.named record containing a base_url, name, key_env and discover_models=true. The native resolver must not supply inventory for this endpoint.
Expected: display-only branding, owned endpoint/key/headers for inventory, existing profile-aware cache/refresh, and explicit catalog effort metadata rather than invented graded support.
Actual: configured names were ignored and provider_model_ids did not resolve the named route. reasoning=true was treated as a complete effort ladder.
Root cause: the picker/live endpoint bypassed the custom route bundle; boolean capability information was overloaded as effort-level metadata.
Change: reuse the existing route bundle and credential/header-scoped API cache; make configured failure authoritative; honor configured name and opt-in catalog effort values.
Verification: 97 targeted tests pass across named catalog, discovered-list semantics, live cache/custom probe, case handling, profile cache, metadata reasoning and over-budget fallbacks. Both immediate and over-budget cold-cache failures suppress retired settings inventory (explicit configured defaults remain visible). Ambiguous records suppress only their route; built-in/plugin catalogs keep their existing reader. The discovery gate and connection bundle share record selection. Catalog effort lookup, tuned overrides and stale-level coercion follow mixed-case and custom-prefixed live routes; import/lookup failure exposes no invented ladder. Branding preserves default injection and ignores blank names. Isolated live integration matched 23 provider IDs and catalog entries. This is not full-window inference certification or production UI verification.
Compatibility / risk: generic opt-in named routes are affected; stable IDs remain unchanged. New Agent ModelCapabilities.reasoning_efforts is optional via getattr, so old Agent versions keep existing behavior. Metadata may lag API inventory.
Maintenance owner: fork maintainers; rebase surface api/config.py and api/routes.py.
Rollback: revert this logical change and restore the previous explicit provider inventory policy before restarting consumers; no state migration.
Upstream status: issue-ready, not filed. Reconstruct the public-safe delta on current upstream before contribution; do not submit fork ancestry.
Private details removed: yes.
