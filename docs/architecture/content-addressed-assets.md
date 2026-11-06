# Content-addressed shell assets

Shell/login asset URLs use SHA-256 content identities. The bounded fingerprint cache invalidates on file identity and stat changes. Shell cache keys include referenced asset identities; worker registration and namespace include its rendered manifest and logic. HTML and worker responses remain no-store. Immutable static caching applies only when the requested version equals the returned bytes; obsolete version queries return current bytes with no-store. Git display versions are unchanged. Initial installation needs a backend restart; subsequent compatible static edits gain new URLs without restarting or purging caches. This is not atomic multi-file publication or historical-build storage. Extension assets and unversioned external/vendor assets retain their existing policy.

## Verification

`tests/browser_asset_updates.py` contains isolated regression coverage. The browser harness uses the real isolated server and service worker with a sticky immutable-cache shim, temporary state and no provider calls. It does not establish physical iOS behavior or an actual CDN policy.

## Compatibility and rollback

Worker source and rendered identities are bounded-cache entries; each shell request still checks referenced file signatures so hot edits are detected without a watcher or polling delay. Custom worker templates may retain a standalone application-version token; the shipped template's identity follows content only. On Windows, where Python reports creation time in `st_ctime_ns`, same-size in-place edits with restored mtimes are not detected; use changed mtimes or atomic file replacement. Filesystem timestamp resolution remains a boundary on every platform.

This change is independent of the other long-chat fixes and introduces no dependencies or configuration. Revert this commit to remove it; no state migration is needed. Backend changes require a normal service restart.
