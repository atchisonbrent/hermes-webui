"""Accepted UI inputs are durable display receipts, never model turns."""
import pytest


def test_user_input_receipts_survive_reload_without_turn_state(tmp_path):
    from api.turn_journal import (append_turn_journal_event, record_user_input,
                                  read_user_inputs, read_turn_journal, derive_turn_journal_states)
    append_turn_journal_event('session', {'event':'submitted','turn_id':'turn','stream_id':'run','content':'prompt'},session_dir=tmp_path)
    first=record_user_input('session','steer','Change direction',stream_id='run',session_dir=tmp_path)
    second=record_user_input('session','clarify','Yes',stream_id='run',session_dir=tmp_path)
    assert first['input_id'] != second['input_id']
    assert read_user_inputs('session',session_dir=tmp_path)==[first,second]
    states,collisions=derive_turn_journal_states(read_turn_journal('session',session_dir=tmp_path)['events'])
    assert set(states)=={'turn'}
    assert states['turn']['event']=='submitted'
    assert not collisions
    assert read_user_inputs('other',session_dir=tmp_path)==[]


@pytest.mark.parametrize('kind,text',[('unknown','text'),('steer',''),('clarify','  ')])
def test_invalid_input_is_not_recorded(tmp_path,kind,text):
    from api.turn_journal import record_user_input,read_user_inputs
    with pytest.raises(ValueError):
        record_user_input('session',kind,text,session_dir=tmp_path)
    assert read_user_inputs('session',session_dir=tmp_path)==[]


def test_endpoints_record_only_accepted_inputs_and_report_write_failure(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from api import routes,streaming,config,turn_journal,runtime_adapter
    from tests.test_real_steer import _make_handler,_captured_response
    monkeypatch.setattr(turn_journal,'_default_session_dir',lambda:tmp_path)
    session=SimpleNamespace(active_stream_id='run',messages=[{'role':'user','content':'original'}])
    calls=[]
    agent=SimpleNamespace(session_id='session',steer=lambda text:(calls.append(text) or True))
    monkeypatch.setattr(config,'SESSION_AGENT_CACHE',{'session':(agent,'signature')})
    monkeypatch.setattr(config,'STREAMS',{'run':object()})
    monkeypatch.setattr(streaming,'get_session',lambda sid:session)
    handler=_make_handler()
    streaming._handle_chat_steer(handler,{'session_id':'session','text':'raw transport','display_text':'visible steer'})
    response=_captured_response(handler)
    assert response['accepted'] and response['display_recorded']
    assert calls==['raw transport']
    assert turn_journal.read_user_inputs('session')[0]['content']=='visible steer'
    monkeypatch.setattr(routes,'get_session',lambda sid,**kwargs:session)
    monkeypatch.setattr(runtime_adapter,'runtime_adapter_enabled',lambda:False)
    monkeypatch.setattr(routes,'_resolve_clarify_legacy',lambda *args:True)
    handler=_make_handler()
    routes._handle_clarify_respond(handler,{'session_id':'session','clarify_id':'choice','response':'Yes'})
    response=_captured_response(handler)
    assert response['ok'] and response['display_recorded']
    assert [r['kind'] for r in turn_journal.read_user_inputs('session')]==['steer','clarify']
    assert session.messages==[{'role':'user','content':'original'}]
    monkeypatch.setattr(routes,'_resolve_clarify_legacy',lambda *args:False)
    handler=_make_handler()
    routes._handle_clarify_respond(handler,{'session_id':'session','clarify_id':'stale','response':'Rejected'})
    assert not _captured_response(handler)['ok']
    assert len(turn_journal.read_user_inputs('session'))==2
    def fail(*args,**kwargs):raise OSError('disk full')
    monkeypatch.setattr(turn_journal,'record_user_input',fail)
    handler=_make_handler()
    streaming._handle_chat_steer(handler,{'session_id':'session','text':'accepted once'})
    response=_captured_response(handler)
    assert response['accepted'] and response['display_recorded'] is False
    assert calls==['raw transport','accepted once']
    assert len(turn_journal.read_user_inputs('session'))==2


@pytest.mark.parametrize('load_messages',['0','1'])
def test_session_endpoint_returns_receipts_separate_from_model_messages(tmp_path,monkeypatch,load_messages):
    from urllib.parse import urlparse
    from api import routes,turn_journal
    from tests.test_webui_state_db_reconciliation import _install_test_session,_GetHandler
    messages=[{'role':'user','content':'original','timestamp':1}]
    session=_install_test_session(monkeypatch,tmp_path,'receipt-fixture',messages)
    receipt=turn_journal.record_user_input('receipt-fixture','clarify','Accepted',stream_id='run')
    monkeypatch.setattr(routes,'get_session',lambda *a,**k:session)
    monkeypatch.setattr(routes,'_clear_stale_stream_state',lambda s:None)
    monkeypatch.setattr(routes,'find_run_summary',lambda s:None)
    if load_messages=='0':
        def unexpected_read(*args,**kwargs):raise AssertionError('metadata poll read journal')
        monkeypatch.setattr(turn_journal,'read_user_inputs',unexpected_read)
    handler=_GetHandler(f'/api/session?session_id=receipt-fixture&messages={load_messages}&resolve_model=0')
    routes.handle_get(handler,urlparse(handler.path))
    assert handler.status==200
    if load_messages=='1':
        assert handler.response_json['session']['_user_inputs']==[receipt]
    else:
        assert '_user_inputs' not in handler.response_json['session']
    assert session.messages==messages


def test_receipt_redaction_keeps_ids_and_raw_journal_intact(monkeypatch):
    from api import helpers,config
    from tests.test_security_redaction import _FAKE_SK_KEY
    monkeypatch.setattr(config,'load_settings',lambda:{'api_redact_enabled':True})
    receipt={'input_id':'stable-id','stream_id':'stable-stream','kind':'steer','timestamp':1,'content':_FAKE_SK_KEY}
    safe=helpers.redact_session_data({'_user_inputs':[receipt]})['_user_inputs'][0]
    assert safe['content'] != receipt['content']
    assert safe['input_id']==receipt['input_id'] and safe['stream_id']==receipt['stream_id']
    assert receipt['content']==_FAKE_SK_KEY


@pytest.mark.parametrize('kind',['steer','clarify'])
def test_accepted_response_redacts_receipt_without_changing_agent_input(tmp_path,monkeypatch,kind):
    from types import SimpleNamespace
    from api import routes,streaming,config,turn_journal,runtime_adapter
    from tests.test_real_steer import _make_handler,_captured_response
    from tests.test_security_redaction import _FAKE_SK_KEY
    monkeypatch.setattr(turn_journal,'_default_session_dir',lambda:tmp_path)
    monkeypatch.setattr(config,'load_settings',lambda:{'api_redact_enabled':True})
    session=SimpleNamespace(active_stream_id='run')
    accepted=[]
    agent=SimpleNamespace(session_id='session',steer=lambda text:(accepted.append(text) or True))
    monkeypatch.setattr(config,'SESSION_AGENT_CACHE',{'session':(agent,'signature')})
    monkeypatch.setattr(config,'STREAMS',{'run':object()})
    monkeypatch.setattr(streaming,'get_session',lambda sid:session)
    monkeypatch.setattr(routes,'get_session',lambda sid,**kwargs:session)
    monkeypatch.setattr(runtime_adapter,'runtime_adapter_enabled',lambda:False)
    monkeypatch.setattr(routes,'_resolve_clarify_legacy',lambda sid,clarify_id,text:(accepted.append(text) or True))
    handler=_make_handler()
    if kind=='steer':
        streaming._handle_chat_steer(handler,{'session_id':'session','text':_FAKE_SK_KEY})
    else:
        routes._handle_clarify_respond(handler,{'session_id':'session','clarify_id':'choice','response':_FAKE_SK_KEY})
    response=_captured_response(handler)
    assert response['display_recorded']
    assert response['user_input']['content'] != _FAKE_SK_KEY
    assert response.get('response') != _FAKE_SK_KEY
    assert accepted==[_FAKE_SK_KEY]
    assert turn_journal.read_user_inputs('session')[0]['content']==_FAKE_SK_KEY


@pytest.mark.parametrize('error',[ValueError('invalid id'),OSError('unreadable journal')])
def test_unavailable_receipts_do_not_break_transcript(tmp_path,monkeypatch,error):
    from urllib.parse import urlparse
    from api import routes,turn_journal
    from tests.test_webui_state_db_reconciliation import _install_test_session,_GetHandler
    messages=[{'role':'user','content':'original','timestamp':1}]
    session=_install_test_session(monkeypatch,tmp_path,'receipt-fixture',messages)
    monkeypatch.setattr(routes,'get_session',lambda *a,**k:session)
    monkeypatch.setattr(routes,'_clear_stale_stream_state',lambda s:None)
    monkeypatch.setattr(routes,'find_run_summary',lambda s:None)
    def unavailable(*args,**kwargs):raise error
    monkeypatch.setattr(turn_journal,'read_user_inputs',unavailable)
    handler=_GetHandler('/api/session?session_id=receipt-fixture&messages=1&resolve_model=0')
    routes.handle_get(handler,urlparse(handler.path))
    assert handler.status==200
    assert handler.response_json['session']['_user_inputs_unavailable'] is True
    assert handler.response_json['session']['messages']==messages


@pytest.mark.parametrize('error',[ValueError('invalid sidecar'),OSError('unreadable sidecar')])
def test_clarification_acceptance_survives_owner_lookup_failure(tmp_path,monkeypatch,error):
    from api import routes,turn_journal,runtime_adapter
    from tests.test_real_steer import _make_handler,_captured_response
    monkeypatch.setattr(turn_journal,'_default_session_dir',lambda:tmp_path)
    lookups=[]
    def failed_lookup(sid,*,metadata_only=False):
        lookups.append(metadata_only)
        raise error
    monkeypatch.setattr(routes,'get_session',failed_lookup)
    monkeypatch.setattr(runtime_adapter,'runtime_adapter_enabled',lambda:False)
    monkeypatch.setattr(routes,'_resolve_clarify_legacy',lambda *args:True)
    handler=_make_handler()
    routes._handle_clarify_respond(handler,{'session_id':'session','clarify_id':'choice','response':'Yes'})
    result=_captured_response(handler)
    assert lookups==[True], 'display owner lookup must not resolve model history'
    assert result['ok'] and result['display_recorded']
    assert result['user_input']['stream_id']==''
    assert turn_journal.read_user_inputs('session')[0]['content']=='Yes'
