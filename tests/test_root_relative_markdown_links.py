"""Settled root-relative artifact links must remain links after Markdown rendering."""
import shutil

import pytest
from tests.test_issue2768_workspace_links import _render

pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='Node.js required for renderer tests')


@pytest.mark.parametrize('wrapper', ['{}', '## {}', '- {}', '> {}', '| File |\n| --- |\n| {} |'])
def test_root_relative_download_link_survives_settlement(wrapper):
    link = '[**Download the EPUB**](/api/file/raw?path=books%2Fstory.epub&session_id=fixture)'
    html = _render(wrapper.format(link))
    assert 'href="/api/file/raw?path=books%2Fstory.epub&amp;session_id=fixture"' in html
    assert '<strong>Download the EPUB</strong></a>' in html
    assert '[<strong>' not in html


@pytest.mark.parametrize('url', ['//other.example/file', '/\\other.example/file', 'javascript:alert(1)', 'data:text/html,test', 'vbscript:msgbox(1)'])
def test_root_relative_links_do_not_enable_unsafe_destinations(url):
    html = _render(f'[download]({url})')
    assert '<a href=' not in html


def test_root_relative_link_inside_fenced_code_remains_literal():
    html = _render('```markdown\n[download](/api/file/raw?path=book.epub)\n```')
    assert '<a href=' not in html
    assert '[download](/api/file/raw?path=book.epub)' in html


def test_root_relative_session_link_uses_existing_navigation():
    html = _render('[session](/session/fixture)')
    assert 'class="session-link"' in html
    assert 'href="/session/fixture"' in html
    ordinary = _render('[report](/session-report)')
    assert 'session-link' not in ordinary
    assert 'href="/session-report"' in ordinary


def test_deep_backslash_destination_is_not_actionable():
    assert '<a href=' not in _render('[download](/a\\b)')


@pytest.mark.parametrize('wrapper', ['{}', '- {}'])
def test_root_relative_image_is_not_reinterpreted_as_link(wrapper):
    html = _render(wrapper.format('![cover](/cover.png)'))
    assert '<a href=' not in html
    assert '![cover](/cover.png)' in html
