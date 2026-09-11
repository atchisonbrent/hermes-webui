#!/usr/bin/env python3
"""Exercise settled-turn reuse through the full renderer, without live state."""
import json
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_conversation_lifecycle import _start_webui_server, _terminate_process
from browser_reconnect_scene_redraw import INIT, session_route, fixture

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='settled-turn-test-') as temp:
        env = {k:os.environ[k] for k in ('PATH','TMPDIR','SYSTEMROOT') if k in os.environ}
        env.update(HOME=temp,HERMES_HOME=temp,HERMES_BASE_HOME=temp,HERMES_CONFIG_PATH=temp+'/config.yaml',HERMES_WEBUI_STATE_DIR=temp+'/webui',HERMES_WEBUI_HOST='127.0.0.1',HERMES_WEBUI_SKIP_ONBOARDING='1',HERMES_WEBUI_AGENT_DIR=temp+'/no-agent')
        proc, log, _, base = _start_webui_server(ROOT,env,Path(temp))
        try:
            with sync_playwright() as pw:
                for engine in os.environ.get('BROWSERS','chromium,webkit').split(','):
                    browser = getattr(pw,engine).launch(headless=True)
                    try:
                        for mode,shape in [(m,s) for m in ['compact_worklog','transparent_stream'] for s in ['scene','legacy']]:
                            context=browser.new_context(viewport={'width':390,'height':844},bypass_csp=True)
                            context.add_init_script(INIT)
                            page=context.new_page()
                            errors=[]
                            page.on('pageerror',lambda e, errors=errors:errors.append(str(e)))
                            messages=[]
                            for i in range(3):
                                scene=fixture(4)['anchor_activity_scene']
                                scene['identity'].update(stream_id='old-'+str(i),run_id='old-'+str(i))
                                for row in scene['activity_rows']:
                                    row['row_id']=str(i)+'-'+row['row_id']
                                    row['tool']['tid']=str(i)+'-'+row['tool']['tid']
                                    row['tool']['snippet']='DETAIL '+str(i)
                                messages.append({'role':'user','content':'Question '+str(i),'_ts':1000+i*10})
                                if shape=='legacy':
                                    tid='legacy-'+str(i)
                                    messages.extend([{'role':'assistant','content':'Checking the file','reasoning':'Inspect the artifact','_turnDuration':2.5,'tool_calls':[{'id':tid,'function':{'name':'terminal','arguments':'{"command":"printf detail"}'}}]}, {'role':'tool','tool_call_id':tid,'content':'DETAIL '+str(i)}])
                                answer={'role':'assistant','content':'## Answer '+str(i),'_ts':1001+i*10}
                                if shape=='scene':answer['_anchor_activity_scene']=scene
                                messages.append(answer)
                            session=dict(session_id='fixture',title='Turn reuse',model='',workspace=temp,messages=messages,message_count=len(messages),tool_calls=[])
                            page.route('**/api/session?*',session_route(session,'fixture',temp))
                            page.route('**/api/chat/start',lambda route:route.fulfill(json={'stream_id':'run-fixture'}))
                            page.goto(base,wait_until='load')
                            deadline=time.monotonic()+30
                            while not page.evaluate("typeof S!=='undefined'&&S._bootReady"):
                                assert time.monotonic()<deadline,'boot timeout'
                                page.wait_for_timeout(50)
                            page.evaluate("mode=>{window._chatActivityDisplayMode=mode;window._virtualizeTranscript=false;window._showThinking=true;window._simplifiedToolCalling=true;window._showTokenUsage=false}",mode)
                            page.evaluate("async()=>await loadSession('fixture')")
                            result=page.evaluate('''()=>{
                                const old=document.querySelector('#msgInner .assistant-turn');
                                if(!old)throw new Error('missing historical turn');
                                const detailCount=old.querySelectorAll('.tool-worklog-group,.tool-card-row').length;
                                const durationCount=old.querySelectorAll('.msg-duration-inline').length;
                                const changes=new MutationObserver(()=>{});
                                changes.observe(document.querySelector('#msgInner'),{childList:true});
                                const priorToolCalls=S.toolCalls;S.toolCalls=[];
                                S.messages.push({role:'user',content:'Another question',_ts:1100});
                                renderMessages({reuseSettledTurns:true,priorToolCalls});
                                const removed=changes.takeRecords().flatMap(r=>Array.from(r.removedNodes));
                                changes.disconnect();
                                if(removed.includes(old))throw new Error('unchanged historical turn was detached for layout');
                                if(!old.isConnected)throw new Error('unchanged historical turn was rebuilt');
                                if(old.querySelectorAll('.msg-duration-inline').length!==durationCount)throw new Error('reuse duplicated duration chip');
                                if(document.querySelectorAll('#msgInner h2').length!==3)throw new Error('answer disappeared or duplicated');
                                if(old.querySelectorAll('.tool-worklog-group,.tool-card-row').length!==detailCount)throw new Error('cached tool details were removed');
                                const summary=old.querySelector('.tool-worklog-summary,.tool-call-group-header');
                                if(summary)summary.click();
                                else old.querySelector('.tool-card-header')?.click();
                                if(!old.textContent.includes('DETAIL 0'))throw new Error('cached detail expansion lost output');
                                if(chatActivityMode()==='transparent_stream'){
                                    const toolRow=old.querySelector('.tool-card-row');
                                    const detail=toolRow&&toolRow.querySelector('.tool-card-detail');
                                    if(!detail||!detail.textContent.includes('DETAIL 0')||toolRow.hasAttribute('data-transparent-detail-deferred'))throw new Error('deferred detail did not materialize');
                                    _decorateTransparentEventRow(toolRow,{type:'tool',toolCall:toolRow._tcData,settled:true,status:'Completed'});
                                    if(toolRow.querySelector('.tool-card-detail')!==detail)throw new Error('open detail was replaced by redecoration');
                                }
                                if(S.messages.some(m=>m.tool_call_id==='legacy-0')){
                                    // The legacy renderer joins results by id across the whole
                                    // transcript. A later correction must invalidate its owner.
                                    S.messages.splice(S.messages.length-1,0,{role:'tool',tool_call_id:'legacy-0',content:'CORRECTED DETAIL'});
                                    renderMessages({reuseSettledTurns:true});
                                    if(old.isConnected)throw new Error('later tool-result correction retained stale owner');
                                    const corrected=document.querySelector('#msgInner .assistant-turn');
                                    const header=corrected.querySelector('.tool-worklog-summary,.tool-call-group-header,.tool-card-header');
                                    if(header)header.click();
                                    if(!corrected.textContent.includes('CORRECTED DETAIL'))throw new Error('corrected tool result not visible');
                                }
                                const beforeEdit=document.querySelector('#msgInner .assistant-turn');
                                const answerIdx=S.messages.findIndex(m=>m.content==='## Answer 0');
                                S.messages[answerIdx].content='## Edited answer';
                                renderMessages({reuseSettledTurns:true});
                                if(beforeEdit.isConnected)throw new Error('edited history retained stale DOM');
                                if(!document.querySelector('#msgInner').textContent.includes('Edited answer'))throw new Error('edit not rendered');
                                const changed=document.querySelector('#msgInner .assistant-turn');
                                renderMessages();
                                if(changed.isConnected)throw new Error('ordinary invalidation reused nodes');
                                return {answers:document.querySelectorAll('#msgInner h2').length};
                            }''')
                            lifecycle=page.evaluate(r'''async()=>{
                                const metadata={...S.session};
                                const before=S.messages.length;
                                $('msg').value='Give me the EPUB';
                                await send();
                                const source=fixtureSources.findLast(s=>s.url.includes('api/chat/stream?')&&s.readyState===1);
                                if(!source)throw new Error('missing stream');
                                const answer='## Download\n\n[**EPUB**](/api/file/raw?path=book.epub)';
                                source.emit('token',{text:answer},'run-fixture:1');
                                await new Promise(r=>setTimeout(r,100));
                                const historical=document.querySelector('#msgInner .assistant-turn');
                                const messages=S.messages.filter(m=>!m._live).map(m=>{const copy={...m};if(copy._pending)delete copy._pending;return copy;});
                                messages.push({role:'assistant',content:answer});
                                const originalRender=renderMessages;let renders=0;
                                renderMessages=function(...args){renders++;return originalRender(...args)};
                                try{
                                    source.emit('done',{session:{...metadata,messages,message_count:messages.length}},'run-fixture:2');
                                    source.emit('stream_end',{},'run-fixture:3');
                                }finally{renderMessages=originalRender;}
                                if(renders!==1)throw new Error('prose-only done rebuilt transcript '+renders+' times');
                                if(!historical.isConnected)throw new Error('done rebuilt unchanged historical activity');
                                if(S.busy||S.messages.length!==before+2)throw new Error('completion state mismatch');
                                const links=Array.from(document.querySelectorAll('#msgInner a')).filter(a=>a.textContent==='EPUB');
                                if(links.length!==1||links[0].getAttribute('href')!=='/api/file/raw?path=book.epub')throw new Error('EPUB link not rendered');
                                const roles=Array.from(document.querySelector('#msgInner').children).map(n=>n.dataset.role).filter(Boolean);
                                if(roles.join(',')!=='user,assistant,user,assistant,user,assistant,user,user,assistant')throw new Error('turn order changed: '+roles);
                                return {renders,link:true};
                            }''')
                            wakeup=page.evaluate('''()=>{
                                S.messages=[{role:'user',content:'Before wakeup'},
                                  {role:'assistant',content:'## Before boundary'},
                                  {role:'assistant',_source:'process_wakeup',content:'Process completed'},
                                  {role:'assistant',content:'## After boundary'},
                                  {role:'user',content:'Next turn'},
                                  {role:'assistant',content:'## Tail answer'}];
                                S.toolCalls=[];S._settledLiveToolMetadata=[];S.session.tool_calls=[];
                                renderMessages();
                                const before=Array.from(document.querySelectorAll('#msgInner h2')).map(n=>n.textContent);
                                S.messages.push({role:'user',content:'One more'});
                                renderMessages({reuseSettledTurns:true});
                                const after=Array.from(document.querySelectorAll('#msgInner h2')).map(n=>n.textContent);
                                if(before.join('|')!=='Before boundary|After boundary|Tail answer'||JSON.stringify(before)!==JSON.stringify(after))throw new Error('wakeup boundary lost or reordered answers');
                                return {answers:after.length};
                            }''')
                            assert wakeup['answers']==3
                            assert not errors,errors
                            print(json.dumps(dict(engine=engine,mode=mode,shape=shape,**result,lifecycle=lifecycle)),flush=True)
                            context.close()
                    finally:browser.close()
        finally:_terminate_process(proc);log.close()

if __name__=='__main__':main()
