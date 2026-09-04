# Content-addressed WebUI shell assets

- Classification: upstream candidate; generic cache-correctness fix.
- Owner: fork maintainers.
- Base: `0b1de4fc8b7c0588211517741feccf1622f4c392`.
- Branch: `fix/content-addressed-assets`.
- Release-note wording: Frontend-only updates now get fresh asset URLs without
  restarting the backend or manually clearing CDN/browser caches.

## Reproduction and cause

Start the server, load a page through an immutable HTTP cache, then edit only
`static/sessions.js`. Previously both the rendered HTML and service worker kept
using the process-start Git version in the URL. The origin reread the file, but
the cache correctly retained its previous response for that unchanged URL.
Network-first service-worker fetching cannot invalidate an upstream cache.

The initial regression test failed because old/new script URLs were identical.
The corrected test holds an immutable old response and proves a changed file
escapes it with a new URL in the same process.

## Contract and implementation

`api/asset_versions.py` owns SHA-256 identities for version-placeholder static
URLs. It hashes file bytes, memoizes hashes in a bounded cache, and invalidates
that cache by device/inode/size/mtime/ctime. No build step, dependency, config,
Git mutation, watcher, purge permission, or additional service is needed.

- HTML and login asset URLs use their individual content identities.
- Shell-template caching includes referenced asset identities, not just the
  template's timestamp. CSRF and extension injection stay per-request.
- The worker's namespace includes worker logic and its rendered asset manifest.
  Its registration URL fingerprints the rendered worker too, avoiding same-URL
  update-check deferral. `updateViaCache: 'none'` keeps worker update requests
  out of the browser HTTP cache; it is not a claim to bypass a CDN.
- HTML and worker responses remain `no-store`. Static responses receive
  `immutable` only when the request names the exact bytes being returned.
  Obsolete/arbitrary version queries receive current bytes with `no-store` for
  old-client compatibility, not a false immutable guarantee. These URLs are not
  an archive of historical builds. Unversioned responses retain their existing
  short cache policy.
- Application display/update-version semantics remain Git-based and unchanged.
- The existing successful-scene reconnect rendering guard is unchanged.

## Boundaries

This solves the existing version-placeholder shell/login paths. Extension-owned
assets, unversioned vendor imports, CSS-relative font URLs, and external CDN
libraries retain their existing owners and cache policies. No forced page
reload, draft deletion, cookie clearing, auth change, or provider/state mutation
is introduced. Cache cleanup/activation policy is otherwise unchanged.

It does not make concurrent multi-file publication atomic, guarantee old-build
availability, or make incompatible frontend/backend releases hot-deployable.
Deploy compatible files as a reviewed set. A file changed between HTML render
and asset fetch cannot earn immutable caching under the wrong hash, but a
reload may still be necessary after an interrupted/incompatible publication.

The first installation changes Python and needs a normal idle/drain-gated
restart. Subsequent compatible frontend-only edits do not need a restart for
new URLs. Do not mistake a merged revision for activated Python.

## Verification

Focused repository-runner suite: content addresses, shell cache, gzip/ETag/304,
selected static root, PWA manifest/worker, session static aliases, anchor load
order, reconnect guard, shell error path, and auth/login headers.

`tests/browser_asset_updates.py` boots the real isolated server with copied
static files and a deliberately sticky immutable-edge shim. Chromium and WebKit
retain their contexts and real workers/CSP across a script-only edit. Checks:
old edge URL remains stale, new HTML gets a new script URL and executes new
bytes, unchanged script URLs stay stable, worker namespace changes, page
reopening works, and the server process does not restart. No browser route
fixtures, SW disabling, production state, provider calls, or cache purge.
One narrowly allowed WebKit reload-time health-probe cancellation is counted
separately and requires a successful current-document health fetch. This is
not physical iPadOS Home Screen testing or a real Cloudflare integration test.

Deployment acceptance additionally requires authenticated public-host readback
of the actual HTML/worker asset URLs and SHA-256 equality to reviewed files,
not just localhost or an invented cache-busting probe. Check headers, health,
and the affected public conversation after activation. Keep deployment status
separate from candidate validation.

## Rollback and upstream decision

Revert this logical change and perform the same idle-gated restart. No state or
schema rollback is necessary. Old content hashes can remain safely cached;
never purge the whole zone or delete an installed PWA as routine rollback.
An old pre-fix process can use Git-versioned URLs again, so verify public bytes
and use an authorized targeted purge only if the old URL is demonstrably stale.

Propose upstream once reviewed and deployment-verified; remove the fork patch
when an equivalent upstream mechanism passes these regressions. Do not publish
private sessions, credentials, hostnames, or local diagnostic logs with it.
