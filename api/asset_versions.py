"""Content identities for file-backed shell assets; no build step or Git state.

Templates retain their existing version placeholders. Only local static URLs
receive byte-derived fingerprints; application version/UI tokens stay separate.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path
import re


_ASSET_URL = re.compile(
    r'(?P<url>(?:\./|/)?static/(?P<name>[A-Za-z0-9_./-]+))'
    r'\?v=(?:__WEBUI_VERSION__|\{\{WEBUI_VERSION\}\})'
)


def file_signature(path: Path) -> tuple:
    """Include identity/ctime: atomic replaces and preserved mtimes are edits too."""
    st = path.stat()
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def content_version(data: bytes) -> str:
    return 'sha256-' + hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=256)
def _file_version(path: Path, signature: tuple) -> str:
    # The signature invalidates the bounded cache, it is not the public identity.
    return content_version(path.read_bytes())


def asset_replacements(template: str, static_root: Path) -> tuple:
    """Resolve each distinct template URL once. Never fingerprint missing files."""
    root = static_root.resolve()
    replacements = {}
    for match in _ASSET_URL.finditer(template):
        original = match.group(0)
        if original in replacements:
            continue
        path = (root / match['name']).resolve()
        try:
            path.relative_to(root)
            version = _file_version(path, file_signature(path))
            replacement = match['url'] + '?v=' + version
        except (FileNotFoundError, ValueError):
            # Preserve the normal 404 for incomplete/custom static trees without
            # reading escaped paths or promising immutable nonexistent bytes.
            replacement = match['url']
        replacements[original] = replacement
    return tuple(replacements.items())


def apply_asset_replacements(template: str, replacements: tuple) -> str:
    mapping = dict(replacements)
    return _ASSET_URL.sub(lambda match: mapping[match.group(0)], template)


def render_asset_urls(template: str, static_root: Path) -> str:
    return apply_asset_replacements(template, asset_replacements(template, static_root))


def render_service_worker(template: str, static_root: Path, version: str) -> str:
    rendered = render_asset_urls(template, static_root).replace('__WEBUI_VERSION__', version)
    # The namespace follows both worker logic and its exact asset manifest.
    # Hash with the cache-name placeholder intact to avoid a circular identity.
    return rendered.replace('__ASSET_VERSION__', content_version(rendered.encode('utf-8')))


def service_worker_version(static_root: Path, version: str) -> str:
    """A new registration URL requests an update even within browser throttles."""
    try:
        template = (static_root / 'sw.js').read_text(encoding='utf-8')
    except FileNotFoundError:
        # PWA support is optional: retain the shell and let registration's 404
        # reach its existing catch handler, rather than returning a shell 503.
        return ''
    return content_version(render_service_worker(template, static_root, version).encode('utf-8'))
