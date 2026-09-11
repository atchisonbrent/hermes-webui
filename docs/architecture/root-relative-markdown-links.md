# Root-relative Markdown links

The settled Markdown renderer accepts root-relative HTTP destinations such as `/api/file/raw?...` in paragraphs, headings, lists, blockquotes and tables. These are not workspace-relative filesystem paths. Existing endpoint authorization remains responsible for file access. Protocol-relative URLs, backslashes, control characters and executable schemes are not enabled. `/session/<id>` links use the existing session-navigation action; other root paths remain ordinary links. Session-navigation classes still require an internal session destination. Code fences and unsupported root-relative image syntax remain literal.

Subpath limitation: `/api/...` still resolves at the host root, not under a mount such as `/hermes/`. Authors must include the actual mount prefix when needed; the renderer does not silently change destinations.

## Verification

`tests/test_root_relative_markdown_links.py` contains isolated regression coverage. `tests/browser_root_relative_markdown_links.py` exercises the real renderer in Chromium/WebKit at desktop and phone widths, without a model call or file download. It does not establish physical iOS behavior.

Run `./scripts/test.sh tests/test_root_relative_markdown_links.py` and, with Playwright Chromium/WebKit installed, `.venv/bin/python tests/browser_root_relative_markdown_links.py`. The browser check is manual, not part of hosted CI.

## Compatibility and rollback

This frontend-only change introduces no dependencies or configuration. Revert this commit to remove it; no state migration is needed. Clients must load the updated JavaScript.
