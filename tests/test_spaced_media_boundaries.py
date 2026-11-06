"""Spaced MEDIA tokens retain the same authorization and share boundaries."""
from api.routes import _MEDIA_TOKEN_RE
from api.shares import _embed_share_media


def test_session_media_token_accepts_space_without_crossing_lines():
    assert _MEDIA_TOKEN_RE.findall('MEDIA: /tmp/chart.png') == ['/tmp/chart.png']
    assert _MEDIA_TOKEN_RE.findall('MEDIA:\n/tmp/chart.png') == []


def test_spaced_local_media_cannot_escape_public_share_roots(tmp_path):
    text = f'MEDIA: {tmp_path}/private.png'
    rendered = _embed_share_media(text, allowed_roots=())
    assert 'MEDIA:' not in rendered
    assert str(tmp_path) not in rendered
    assert '<img' not in rendered


def test_spaced_external_media_is_not_read_as_local_file():
    text = 'MEDIA: https://example.com/image.png'
    assert _embed_share_media(text, allowed_roots=()) == text
