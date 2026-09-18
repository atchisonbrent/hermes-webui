"""Exact run-owned user boundaries survive display pagination."""
from types import SimpleNamespace

import pytest


def session(**overrides):
    return SimpleNamespace(**(dict(active_stream_id='run', pending_started_at=10) | overrides))


def test_boundary_uses_full_merged_transcript():
    from api.routes import _active_turn_display_boundary
    rows = [dict(role='user', timestamp=1), dict(role='assistant', content='Older answer'),
            dict(role='user', timestamp=10), dict(role='assistant', reasoning='Working')]
    assert _active_turn_display_boundary(session(), rows) == dict(stream_id='run', user_index=2)
    assert rows[2] == dict(role='user', timestamp=10)  # projection only


@pytest.mark.parametrize('rows', [
    [], [dict(role='user', timestamp=9.999)], [dict(role='assistant', timestamp=10)],
    [dict(role='user', timestamp=10), dict(role='user', timestamp=11)],
    [dict(role='user', timestamp=10), dict(role='user', timestamp=10)],
])
def test_ambiguous_or_noncurrent_boundary_is_not_guessed(rows):
    from api.routes import _active_turn_display_boundary
    assert _active_turn_display_boundary(session(), rows) is None


@pytest.mark.parametrize('started', [None, False, 0, float('nan'), float('inf')])
def test_invalid_pending_identity(started):
    from api.routes import _active_turn_display_boundary
    assert _active_turn_display_boundary(session(pending_started_at=started), [dict(role='user', timestamp=10)]) is None


def test_checkpoint_token_is_authoritative():
    from api.process_event_utils import build_active_turn_token
    from api.routes import _active_turn_display_boundary
    rows = [dict(role='user', timestamp=1, _active_turn_token=build_active_turn_token('run', 10))]
    assert _active_turn_display_boundary(session(), rows) == dict(stream_id='run', user_index=0)


def test_session_endpoint_carries_boundary_outside_page(monkeypatch, tmp_path):
    from urllib.parse import urlparse
    import api.routes as routes
    from tests.test_webui_state_db_reconciliation import _GetHandler, _install_test_session

    rows = [dict(role='user', content='Earlier', timestamp=1),
            dict(role='assistant', content='Earlier answer', timestamp=2),
            dict(role='user', content='Current', timestamp=10)]
    rows += [dict(role='assistant', content=f'Progress {i}', timestamp=11+i) for i in range(35)]
    active = _install_test_session(monkeypatch, tmp_path, 'boundary-fixture', rows)
    active.active_stream_id = 'run'
    active.pending_started_at = 10
    active.pending_user_message = 'Current'
    monkeypatch.setattr(routes, 'get_session', lambda *a, **k: active)
    monkeypatch.setattr(routes, '_clear_stale_stream_state', lambda s: None)
    monkeypatch.setattr(routes, '_active_stream_ids', lambda: {'run'})
    monkeypatch.setattr(routes, 'find_run_summary', lambda s: None)
    handler = _GetHandler('/api/session?session_id=boundary-fixture&messages=1&resolve_model=0&msg_limit=30')
    routes.handle_get(handler, urlparse(handler.path))
    assert handler.status == 200
    payload = handler.response_json['session']
    assert payload['_active_turn_boundary'] == dict(stream_id='run', user_index=2)
    assert payload['_messages_offset'] > 2
    assert len(payload['messages']) == 30
    assert all(m['role']=='assistant' for m in payload['messages'])


def test_browser_boundary_identity_and_fallbacks():
    import json
    import shutil
    import subprocess
    from pathlib import Path
    from tests.test_cross_session_message_load_isolation import _extract_function

    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable')
    source = (Path(__file__).resolve().parents[1]/'static/sessions.js').read_text()
    helper = _extract_function(source, '_restoreActiveTurnWindowBoundary')
    script = helper + """
    const row={role:'assistant',content:'partial'};
    const base={active_stream_id:'run',pending_user_message:'prompt',_messages_offset:11,
      _active_turn_boundary:{stream_id:'run',user_index:10}};
    function getPendingSessionMessage(s){return s.pending_user_message?{role:'user',content:s.pending_user_message,_pending:true}:null;}
    const check=(s)=>_restoreActiveTurnWindowBoundary(s,[row]);
    const restored=check(base);
    const real={role:'user',content:'canonical prompt',attachments:[{name:'proof.txt'}]};
    const expanded=_restoreActiveTurnWindowBoundary({...base,_messages_offset:10},[real,...restored]);
    const cases=[{...base,_active_turn_boundary:null},
      {...base,_active_turn_boundary:{stream_id:'old',user_index:10}},
      {...base,_active_turn_boundary:{stream_id:'run',user_index:-1}},
      {...base,_messages_offset:'11'}, {...base,_messages_offset:0},
      {...base,active_stream_id:null}, {...base,pending_user_message:''}];
    const adopted=_restoreActiveTurnWindowBoundary({...base,_messages_offset:10,pending_attachments:[null,{name:'pending.png'}]},[{role:'user',content:'canonical'}]);
    process.stdout.write(JSON.stringify({adopted:adopted[0].attachments,
      restored:restored.map(m=>m.role),unchanged:cases.every(s=>check(s).length===1),
      expanded:expanded.map(m=>m.role),attachments:expanded[0].attachments,
      canonical:real,rawUnchanged:row,missingIndex:check({...base,_messages_offset:10}).length
    }));
    """
    result = subprocess.run([node, '-e', script], text=True, capture_output=True, check=True)
    data = json.loads(result.stdout)
    assert data.get('adopted') == [dict(name='pending.png')]
    assert data['restored'] == ['user', 'assistant']
    assert data['unchanged']
    assert data['expanded'] == ['user', 'assistant']
    assert data['attachments'] == [dict(name='proof.txt')]
    assert data['canonical'] == dict(role='user', content='canonical prompt', attachments=[dict(name='proof.txt')])
    assert data['rawUnchanged'] == dict(role='assistant', content='partial')
    assert data['missingIndex'] == 1
