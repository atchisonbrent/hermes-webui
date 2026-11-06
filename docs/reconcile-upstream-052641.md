# Upstream v0.52.641 reconciliation and long-session resilience

> Status: **integration candidate**, not a deployment receipt. This records the joint fork update Brent requested to reconcile upstream, preserve existing deployment safeguards, and publish as one combined update. Named-tree test and review results are reported separately; this document does not by itself grant release approval.

## Classification and ownership

**Classification:** local-product-delta, preserving reviewed fork safeguards against a supplied upstream release. The separately applicable public performance work is an upstream candidate and remains recorded in `live-transcript-render-performance.md`.

- Fork deployment baseline: `bd100af59f532fac427f9811782660ba6f6ba27b`.
- Current upstream merge parent: `nesquena/hermes-webui` at `6124ed3c94087dcd5df72ed3062df8e5d9db0f12`.
- Earlier upstream merge baseline: `b2a30e91fae9c296533aeeba81c2f92cc64cdd60`, including `f65960b46351815958e8ce5e0f81585a5764531b` and its six Samsung-SEF follow-up commits. That history remains merged rather than replayed.
- Long-session performance parent: `7525a02f10ce08ac516bf4f9ab3965fc28ceafd0`, based on the same fork deployment baseline named above.
- Preserve deployment, performance and current-upstream merge ancestry. Do not replay fork commits as cherry-picks or rewrite public history.
- Owner: Brent Atchison / fork maintainers.
- Upstream status: not-filed. Candidate mechanisms should be reconstructed on fresh upstream with their own evidence before any future upstream contribution. Local/provider-specific defaults are not silently presented as universally required upstream policies.

## Problems addressed

The stock fork browser could spend tens of seconds on the UI thread in a long, active transcript, despite existing transcript-window recovery. The old reconnect loop and partial virtualization did not explain or fix the dominant shared-string work.

The upstream reconciliation must also preserve fork behavior with existing regression coverage: exact provider and profile identity, per-model defaults and overrides, admission/drain refusal, accepted-input display receipts, protected read-only native sessions, bounded completion delivery, and exact content-addressed static shell assets. Upstream must remain the owner of its newer implementations wherever its behavior is an equivalent or stronger contract; redundant custom implementations are retired rather than duplicated.

## Change and boundaries

- Incorporate v0.52.641 through normal merge history in the fork's deployment worktree.
- Retain only fork-specific safeguards that remain needed. Preserve explicit selected providers/endpoints, per-model efforts, session-local explicit efforts, missing-profile isolation, and the default-off provider/model fallback policy.
- Preserve completion delivery across active-turn admission races without re-marking rejected dispatch retries as agent-consumed. Keep the existing bounded joined-delivery behavior, acknowledgment provenance, and pre-admission draining checks.
- Preserve display receipt history while adopting native upstream worklog, recovery and caching behavior. Do not reintroduce the retired blanket DOM-retention guarantee as a feature or an acceptance test.
- Preserve exact-content asset addressing so in-place server/content changes cannot leave a mixed JavaScript shell or `_runOnce` cache map.
- Do not expose/expand environment-backed credentials during reads or writes. A failed configured live catalog cannot fall through to another provider or resurrect retired static inventory.
- Integrate the independently reviewed cold-render performance topic next: per-render reasoning-echo normalization/reuse, bounded per-signature long-string identity, comparable-cache-first lookup, and cold-load behavior. Any conflicts are resolved against that topic's tests and re-measured on the final merged renderer.

No unrelated Agent upgrade, provider/model migration, default-effort change, changed live preference, agent interruption, or epoch-consuming upstream rebase is included. Only explicitly owned tests and contracts are adapted when upstream's public interface changes.

## Reconciliation regression controls

- Enumeration and single-session metadata lookup share the complete external-source cache identity. Metadata prefix parsing falls back to a full load when the identity field is beyond the prefix, but still rejects a conflicting identity.
- Configured live authority probes share upstream's partial-catalog continuation: an unavailable budget-sliced attempt is retried at the full cap before publication. A real empty response and a successful Agent-cache recovery remain authoritative; neither falls through to another provider.
- Explicit model picks update only that model's override in the checked profile. New sessions snapshot their model's effective default; an explicitly saved session effort wins even when its value happens to equal the profile default. Model-less writes retain the native profile-default behavior.
- Recursive YAML reads retain upstream's unexpanded-document fallback. The credential-preserving writer alone opts into a cycle-preserving comparison graph; readers do not silently acquire different expansion semantics.
- Summary placement beside the final ordinary-chat prose does not rearrange a delegated subagent's deliberately interleaved worklogs.
- Compatibility fixtures execute the moved recovery, cache and message-window helpers rather than assuming their old inline source shape. Content-addressed asset tests use the actual content fingerprint, including stale-fingerprint negative controls.

## Verification so far and required gates

Observed before this record's final tree pin:

- The broader focused suite passed 297 tests, including provider catalog authority, Jpeg redaction, reasoning rendering and virtualization-cache contracts. The named catalog suite separately passed 20 cases, covering native live inventory, failed probes, scheduled timeouts, completed background publication, legacy API-field routing, option IDs and curated allowlists.
- The verified frozen-session UI replays retained 5,891 messages in both native retained rendering and the existing opt-in virtualized mode. Full-history loading, controlled reasoning and live-stream callbacks, disclosure, typing, reconnect and cached-reload checks passed in 390-pixel Playwright WebKit. That is browser emulation, not physical-iOS validation. Controlled full redraws are stress measurements, not a blanket DOM-retention contract.
- The existing experimental virtualization option remains opt-in and default-off. Its measured redraw benefit does not silently change the user's preference or become a default-on experimental feature.
- A separate, three-file Agent redaction patch retained the same canonical serialized public projection as the production redactor in repeated controlled runs. Its representative full-projection comparison reduced elapsed time by about 1.72 seconds while keeping message/tool-call counts and output digests equal. The Agent change requires its own review, commit and coordinated deployment; it is not a general Agent upgrade.

Required before `[verified]`, publication or activation:

- Full affected regression and browser matrix on the final merged tree, including the real permission/default activity-visible large-session case, with the separately authorized Agent source checked explicitly where backend redaction is measured.
- Static cache parity/collision checks and current integrated `ui.js` replay of the original private session through isolated, metrics-only browser fixtures. No transcript text or credential payload enters evidence reports or independent review.
- Profile/config raw-write, named live catalog, model/provider routing, lifecycle/admission, history/receipt/reconnect and static-asset checks.
- Same-code full-suite attribution against pristine upstream. No broad-suite badge is inferred from focused passes or old progress.
- Exact-tree paired independent reviews of the complete intentional fork delta against the current upstream parent, plus explicit verification of merge ancestry and upstream-owned content. Earlier narrow reviews do not attest to the integrated candidate. Reviewing a fork delta does not claim that every historical upstream commit has been independently re-reviewed here.
- Supported, drain-gated deployment of backend plus static assets, real HTTP health/equivalent served revision, isolated startup and rollback evidence. Pushing code is not proof the running application switched revisions.

## Compatibility and rollback

Transcript/history storage and profile-local identities remain canonical. Do not force cache format changes, delete state, vendor environment values, or make an ambiguous delivery retry restart state-changing work. No static cache marker may bypass ownership of the actual response HTML.

Revert the combined merge/topic series on the fork if necessary; retain its review history. For activation failure, use the existing supported WebUI rollback route to restore the reviewed `bd100af` generation and verify health independently. Do not restore preferences, transcript files or databases by default. Resolve live drain/ownership guards before any live restart; queued update jobs do not override this requirement.

The major remaining rebase surfaces are the transcript renderer/recovery, provider catalog identity, session reasoning precedence, lifecycle admission, and credential-preserving writes. Reassess fork-only seams when upstream supplies equivalent supported behavior; remove redundant policy wrappers rather than keeping parallel caches or ownership registries.
