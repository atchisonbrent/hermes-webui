"""A hot asset edit must escape an immutable CDN entry without a restart."""
import hashlib
import re
from urllib.parse import urlparse

import api.config as config
import api.routes as routes
from tests.test_static_asset_compression_and_cache import _FakeHandler


def _script_url(html):
    return re.search(r'src="([^"]*sessions.js[^"]*)"', html).group(1)


def test_hot_edit_changes_url_and_escapes_cached_bytes(tmp_path, monkeypatch):
    root = tmp_path / 'static'
    root.mkdir()
    index = root / 'index.html'
    index.write_text('<script src="static/sessions.js?v=__WEBUI_VERSION__"></script>')
    script = root / 'sessions.js'
    script.write_bytes(b'old code')
    monkeypatch.setattr(config, 'get_static_root', lambda: root)
    monkeypatch.setattr(config, 'get_index_html_path', lambda: index)
    monkeypatch.setattr(routes, '_INDEX_SHELL_CACHE', {})
    monkeypatch.setattr(routes, '_STATIC_CACHE', {})
    old_url = _script_url(routes._render_index_shell_base())
    edge_cache = {old_url: script.read_bytes()}
    script.write_bytes(b'new code')  # same size, same process, unchanged index
    new_url = _script_url(routes._render_index_shell_base())
    assert new_url != old_url
    assert new_url not in edge_cache
    h = _FakeHandler()
    routes._serve_static(h, urlparse('/' + new_url))
    assert bytes(h.body) == b'new code'
    assert h.header('Cache-Control') == 'public, max-age=31536000, immutable'
    assert 'sha256-' + hashlib.sha256(bytes(h.body)).hexdigest() in new_url


def test_rendered_html_and_worker_share_exact_asset_urls():
    from api.asset_versions import render_service_worker
    root = config.get_static_root()
    html = routes._render_index_shell_base()
    worker = render_service_worker((root / 'sw.js').read_text(), root, 'fixed-git-version')
    html_urls = set(re.findall(r'static/[A-Za-z0-9_./-]+\?v=sha256-[a-f0-9]+', html))
    worker_urls = set(re.findall(r'static/[A-Za-z0-9_./-]+\?v=sha256-[a-f0-9]+', worker))
    assert any('sessions.js?' in url for url in html_urls)
    assert html_urls <= worker_urls  # worker also prefetches lazy vendor assets
    for url in html_urls:
        name, version = url.removeprefix('static/').split('?v=')
        assert version == 'sha256-' + hashlib.sha256((root / name).read_bytes()).hexdigest()
    assert '__ASSET_VERSION__' not in worker
    assert '__WEBUI_VERSION__' not in worker


def test_worker_namespace_follows_asset_and_worker_edits(tmp_path):
    from api.asset_versions import render_service_worker
    asset = tmp_path / 'a.js'
    asset.write_bytes(b'old')
    template = "const C='__ASSET_VERSION__'; const A=['./static/a.js?v=__WEBUI_VERSION__'];"
    first = render_service_worker(template, tmp_path, 'fixed')
    assert first == render_service_worker(template, tmp_path, 'fixed')
    asset.write_bytes(b'new')
    second = render_service_worker(template, tmp_path, 'fixed')
    assert first != second
    assert first.split(';')[0] != second.split(';')[0]
    third = render_service_worker(template + '// worker edit', tmp_path, 'fixed')
    assert third.split(';')[0] != second.split(';')[0]
    asset.write_bytes(b'old')
    assert first == render_service_worker(template, tmp_path, 'fixed')


def test_preserved_mtime_and_same_size_cannot_hide_hot_edit(tmp_path, monkeypatch):
    import os
    from api.asset_versions import render_asset_urls
    asset = tmp_path / 'a.js'
    asset.write_bytes(b'old')
    stamp = asset.stat()
    template = 'static/a.js?v=__WEBUI_VERSION__'
    old = render_asset_urls(template, tmp_path)
    monkeypatch.setattr(config, 'get_static_root', lambda: tmp_path)
    h = _FakeHandler()
    routes._serve_static(h, urlparse('/' + old))
    asset.write_bytes(b'new')
    os.utime(asset, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    new = render_asset_urls(template, tmp_path)
    assert old != new
    h = _FakeHandler()
    routes._serve_static(h, urlparse('/' + new))
    assert bytes(h.body) == b'new'
    assert 'immutable' in h.header('Cache-Control')


def test_obsolete_and_arbitrary_versions_are_not_immutable(tmp_path, monkeypatch):
    asset = tmp_path / 'a.js'
    asset.write_bytes(b'new')
    monkeypatch.setattr(config, 'get_static_root', lambda: tmp_path)
    old = 'sha256-' + hashlib.sha256(b'old').hexdigest()
    valid = 'sha256-' + hashlib.sha256(b'new').hexdigest()
    for query in ('v=old-git-tag', 'v=' + old, 'v=' + valid + '&v=other'):
        h = _FakeHandler()
        routes._serve_static(h, urlparse('/static/a.js?' + query))
        assert h.status == 200
        assert bytes(h.body) == b'new'
        assert h.header('Cache-Control') == 'no-store'


def test_unchanged_asset_url_survives_other_asset_edit(tmp_path):
    from api.asset_versions import render_asset_urls
    (tmp_path / 'a.js').write_bytes(b'a')
    (tmp_path / 'b.js').write_bytes(b'b')
    template = 'static/a.js?v=__WEBUI_VERSION__ static/b.js?v=__WEBUI_VERSION__'
    first = render_asset_urls(template, tmp_path).split()
    (tmp_path / 'b.js').write_bytes(b'changed')
    second = render_asset_urls(template, tmp_path).split()
    assert first[0] == second[0]
    assert first[1] != second[1]


def test_missing_asset_is_not_given_a_fake_fingerprint(tmp_path):
    from api.asset_versions import render_asset_urls
    assert render_asset_urls('static/missing.js?v=__WEBUI_VERSION__', tmp_path) == 'static/missing.js'


def test_login_uses_current_asset_hash_and_no_store(monkeypatch):
    monkeypatch.setattr(routes, 'load_settings', lambda: {})
    monkeypatch.setattr(routes, '_oidc_login_html', lambda _: '')
    h = _FakeHandler()
    routes.handle_get(h, urlparse('/login'))
    assert h.status == 200
    expected = hashlib.sha256((config.get_static_root() / 'login.js').read_bytes()).hexdigest()
    assert 'static/login.js?v=sha256-' + expected in bytes(h.body).decode()
    assert h.header('Cache-Control') == 'no-store'


def test_entrypoints_revalidate_and_keep_application_version():
    from urllib.parse import quote
    from api.updates import WEBUI_VERSION
    html = routes._render_index_shell_base()
    assert "window.__HERMES_WEBUI_BUNDLE_VERSION__='" + quote(WEBUI_VERSION, safe='') + "'" in html
    h = _FakeHandler()
    routes.handle_get(h, urlparse('/sw.js?v=unchanged-startup-version'))
    assert h.status == 200
    assert h.header('Cache-Control') == 'no-store'
    assert h.header('Service-Worker-Allowed') == '/'
    assert b'hermes-shell-sha256-' in bytes(h.body)
    assert "updateViaCache: 'none'" in html


def test_missing_worker_does_not_prevent_shell_render(tmp_path, monkeypatch):
    index = tmp_path / 'index.html'
    index.write_text('<script>register("sw.js?v=__SERVICE_WORKER_VERSION__")</script>')
    monkeypatch.setattr(config, 'get_static_root', lambda: tmp_path)
    monkeypatch.setattr(config, 'get_index_html_path', lambda: index)
    assert 'sw.js?v=' in routes._render_index_shell_base()
    (tmp_path / 'sw.js').write_text("const C='__ASSET_VERSION__';")
    assert 'sw.js?v=sha256-' in routes._render_index_shell_base()


def test_outside_root_asset_is_never_read_or_fingerprinted(tmp_path):
    from api.asset_versions import render_asset_urls
    root = tmp_path / 'static'
    root.mkdir()
    outside = tmp_path / 'outside.js'
    outside.write_text('outside')
    (root / 'linked.js').symlink_to(outside)
    assert render_asset_urls('static/../outside.js?v=__WEBUI_VERSION__', root) == 'static/../outside.js'
    assert render_asset_urls('static/linked.js?v=__WEBUI_VERSION__', root) == 'static/linked.js'
