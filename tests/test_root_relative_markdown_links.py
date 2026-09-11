"""Settled root-relative artifact links must remain links after Markdown rendering."""
import pytest
from tests.test_issue2768_workspace_links import _render


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
