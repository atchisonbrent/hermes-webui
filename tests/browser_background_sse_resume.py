#!/usr/bin/env python3
"""Exercise hidden SSE failure, elapsed cleanup, and foreground catch-up.

Visibility and elapsed timers are deterministic seams, not physical iOS suspension.
"""
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_conversation_lifecycle import _start_webui_server, _terminate_process
from browser_reconnect_scene_redraw import INIT, fixture, session_route

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='background-sse-') as temp:
        state=Path(temp)
        env={k:os.environ[k] for k in ('PATH','SYSTEMROOT','TMPDIR') if k in os.environ}
        env.update(HOME=temp,HERMES_HOME=temp,HERMES_BASE_HOME=temp,
                   HERMES_WEBUI_STATE_DIR=str(state/'webui'),HERMES_CONFIG_PATH=str(state/'config.yaml'),
                   HERMES_WEBUI_HOST='127.0.0.1',HERMES_WEBUI_SKIP_ONBOARDING='1',
                   HERMES_WEBUI_AGENT_DIR=str(state/'no-agent'))
        proc,log,_,base=_start_webui_server(ROOT,env,state)
        try:
            with sync_playwright() as pw:
                for engine in os.environ.get('BROWSERS','chromium,webkit').split(','):
                    browser=getattr(pw,engine).launch()
                    try:
                        page=browser.new_page(viewport={'width':390,'height':844},bypass_csp=True)
                        page.add_init_script(INIT+"""
window.testHidden=false;
Object.defineProperty(document,'hidden',{get:()=>testHidden});
Object.defineProperty(document,'visibilityState',{get:()=>testHidden?'hidden':'visible'});
window.registryTimers=[];
const nativeTimeout=window.setTimeout;
window.setTimeout=function(fn,delay,...args){
 if(delay===600000&&String(fn).includes('_anchorRegistryMap')){registryTimers.push(fn);return -1;}
 return nativeTimeout(fn,delay,...args);
};
""")
                        page.add_init_script('window.errorOnReturn='+('true' if os.environ.get('ERROR_ON_RETURN')=='1' else 'false')+';')
                        session: dict = dict(session_id='fixture',messages=[],message_count=0,tool_calls=[],workspace=temp,
                                     active_stream_id='run-fixture',pending_user_message='Inspect fixture',
                                     pending_started_at=1,runtime_journal_snapshot=fixture(470))
                        page.route('**/api/session?*',session_route(session,'fixture',temp))
                        page.route('**/api/chat/stream/status?*',lambda r:r.fulfill(json={'active':bool(session['active_stream_id'])}))
                        page.goto(base,wait_until='load')
                        deadline=time.monotonic()+30
                        while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                            assert time.monotonic()<deadline
                            page.wait_for_timeout(50)
                        page.evaluate("async()=>{window._chatActivityDisplayMode='compact_worklog';await loadSession('fixture');}")
                        if os.environ.get('SIBLING_TIMER')=='1':
                            page.evaluate("""async()=>{
                              const end=performance.now()+5000;
                              while(!LIVE_STREAMS.fixture?.source&&performance.now()<end)await new Promise(r=>setTimeout(r,10));
                              const old=LIVE_STREAMS.fixture.source;
                              old.close();
                              await loadSession('fixture',{force:true});
                              while(LIVE_STREAMS.fixture?.source===old&&performance.now()<end)await new Promise(r=>setTimeout(r,10));
                              if(LIVE_STREAMS.fixture?.source===old)throw new Error('no sibling closure');
                            }""")
                        result=page.evaluate("""async()=>{
 const wait=async test=>{const end=performance.now()+5000;while(!test()&&performance.now()<end)await new Promise(r=>setTimeout(r,10));if(!test())throw new Error('resume did not connect');};
 await wait(()=>!!LIVE_STREAMS.fixture?.source&&registryTimers.length>0);
 const old=LIVE_STREAMS.fixture.source;old.emit('open',{});
 const registry=_liveAnchorRegistries.get('run-fixture');
 testHidden=true;document.dispatchEvent(new Event('visibilitychange'));
 if(!errorOnReturn){old.readyState=2;old.emit('error',{});}
 await new Promise(r=>setTimeout(r,20));
 registryTimers.splice(0).forEach(fn=>fn());
 const retained=_liveAnchorRegistries.get('run-fixture')===registry;
 window.suspendedSource=old;
 return retained;
}""")
                        assert result, 'hidden recovery lost registry'
                        scenario=os.environ.get('RESUME_SCENARIO','snapshot')
                        has_snapshot=scenario in ('snapshot','slow','switch','attachslow')
                        if scenario=='attachslow':
                            probes=[]
                            def delayed_attach(route):
                                probes.append(1)
                                if len(probes)==2:
                                    page.wait_for_timeout(250)
                                    assert page.evaluate("fixtureSources.slice(fixtureSources.indexOf(suspendedSource)+1).filter(s=>s.url.includes('api/chat/stream?')).length")==0,'stale transport wired during preflight'
                                route.fulfill(json={'active':True})
                            page.unroute('**/api/chat/stream/status?*')
                            page.route('**/api/chat/stream/status?*',delayed_attach)
                        if scenario in ('transient','replay','rehide'):
                            probes=[]
                            def probe(route):
                                probes.append(1)
                                if scenario in ('transient','rehide') and len(probes)<=3:
                                    route.abort('failed')
                                elif scenario=='rehide' and len(probes)==4:
                                    page.evaluate("""()=>{
                                      testHidden=true;document.dispatchEvent(new Event('visibilitychange'));
                                      setTimeout(()=>{testHidden=false;document.dispatchEvent(new Event('visibilitychange'));},500);
                                    }""")
                                    route.fulfill(json={'active':False})
                                else:
                                    route.fulfill(json={'active':scenario in ('transient','rehide'),'replay_available':scenario=='replay'})
                            page.unroute('**/api/chat/stream/status?*')
                            page.route('**/api/chat/stream/status?*',probe)
                        session['runtime_journal_snapshot']={**fixture(510),'last_seq':1080,'last_event_id':'run-fixture:1080'} if has_snapshot else None
                        if scenario in ('slow','switch'):
                            held=[]
                            page.unroute('**/api/chat/stream/status?*')
                            page.route('**/api/chat/stream/status?*',lambda r:r.fulfill(json={'active':True}) if held else held.append(r))
                            page.evaluate("()=>{testHidden=false;document.dispatchEvent(new Event('visibilitychange'));if(errorOnReturn){suspendedSource.readyState=2;suspendedSource.emit('error',{});}}")
                            deadline=time.monotonic()+5
                            while not held:
                                assert time.monotonic()<deadline,'no pending recovery request'
                                page.wait_for_timeout(20)
                            assert page.evaluate("()=>{registryTimers.splice(0).forEach(fn=>fn());return _liveAnchorRegistries.has('run-fixture');}"),'registry expired during async recovery'
                            if scenario=='switch':
                                page.evaluate("async()=>{await loadSession('idle-fixture');}")
                            held[0].fulfill(json={'active':True})
                            if scenario=='switch':
                                page.wait_for_timeout(200)
                                assert page.evaluate('S.session.session_id')=='idle-fixture','resume stole navigation'
                                print(engine,scenario,'navigation preserved',flush=True)
                                continue
                        if scenario=='settled':
                            session.update(active_stream_id=None,pending_user_message='',messages=[
                                dict(role='user',content='Inspect fixture',timestamp=1),
                                dict(role='assistant',content='Completed while away',timestamp=2)],message_count=2)
                            settled=page.evaluate("""async()=>{
 testHidden=false;document.dispatchEvent(new Event('visibilitychange'));
 if(errorOnReturn){suspendedSource.readyState=2;suspendedSource.emit('error',{});}
 const end=performance.now()+10000;
 while(S.busy&&performance.now()<end)await new Promise(r=>setTimeout(r,20));
 return {busy:S.busy,answer:document.getElementById('msgInner').textContent.includes('Completed while away')};
}""")
                            assert settled==dict(busy=False,answer=True),settled
                            print(engine,scenario,settled,flush=True)
                            continue
                        result=page.evaluate("""async()=>{
 const old=window.suspendedSource;
 const wait=async test=>{const end=performance.now()+10000;while(!test()&&performance.now()<end)await new Promise(r=>setTimeout(r,10));if(!test())throw new Error('resume did not connect');};
 let renders=0;const render=window._renderLiveAnchorActivitySceneForStream;
 window._renderLiveAnchorActivitySceneForStream=function(...args){renders++;return render(...args);};
 const started=performance.now();
 testHidden=false;document.dispatchEvent(new Event('visibilitychange'));
 if(errorOnReturn){old.readyState=2;old.emit('error',{});}
 await wait(()=>!!LIVE_STREAMS.fixture?.source&&LIVE_STREAMS.fixture.source!==old);
 const fresh=LIVE_STREAMS.fixture.source;fresh.emit('open',{});
 await new Promise(r=>setTimeout(r,100));
 const restored=document.querySelectorAll('#liveAssistantTurn [data-anchor-row-role="tool"]').length;
 const restoreRenders=renders;
 fresh.emit('tool',{name:'terminal',tid:'after-resume',args:{command:'printf resumed'},preview:'resumed'});
 fresh.emit('tool_complete',{name:'terminal',tid:'after-resume',preview:'resumed',duration:1});
 const elapsed=performance.now()-started;
 window._renderLiveAnchorActivitySceneForStream=render;
 return {busy:S.busy,restored,tools:document.querySelectorAll('#liveAssistantTurn [data-anchor-row-role="tool"]').length,renders:restoreRenders,elapsed,url:fresh.url,newUrls:fixtureSources.slice(fixtureSources.indexOf(old)+1).filter(s=>s.url.includes('api/chat/stream?')).map(s=>s.url)};
}""")
                        print(engine,result,flush=True)
                        expected=510 if has_snapshot else 470
                        if has_snapshot:
                            assert len(result['newUrls'])==1 and 'after_seq=1080' in result['newUrls'][0],result
                        assert result['restored']==expected,result
                        assert result['busy'] and result['tools']==expected+1,result
                        assert result['renders']<=5,result
                        assert ('after_seq=1080' if has_snapshot else 'after_seq=1000') in result['url'],result
                        if scenario=='replay':
                            terminal={**session,'active_stream_id':None,'runtime_journal_snapshot':None,
                                      'messages':[dict(role='user',content='Inspect fixture'),dict(role='assistant',content='Recovered terminal answer')],'message_count':2}
                            settled=page.evaluate("""async payload=>{
                              LIVE_STREAMS.fixture.source.emit('done',{session:payload});
                              const end=performance.now()+5000;
                              while(S.busy&&performance.now()<end)await new Promise(r=>setTimeout(r,20));
                              return {busy:S.busy,answer:document.getElementById('msgInner').textContent.includes('Recovered terminal answer')};
                            }""",terminal)
                            assert settled==dict(busy=False,answer=True),settled
                            print(engine,'replay terminal',settled,flush=True)
                            continue
                        latch=page.evaluate("""()=>{
 const source=LIVE_STREAMS.fixture.source;
 testHidden=true;document.dispatchEvent(new Event('visibilitychange'));
 testHidden=false;document.dispatchEvent(new Event('visibilitychange'));
 source.emit('reasoning',{text:'Foreground progress'});
 return LIVE_STREAMS.fixture.wasHidden;
}""")
                        assert latch is False,'healthy foreground progress did not clear suspension latch'
                        released=page.evaluate("""()=>{
 closeLiveStream('fixture');
 registryTimers.splice(0).forEach(fn=>fn());
 return !_liveAnchorRegistries.has('run-fixture');
}""")
                        assert released,'abandoned registry leaked'
                    finally:browser.close()
        finally:
            _terminate_process(proc)
            log.close()


if __name__=='__main__':main()
