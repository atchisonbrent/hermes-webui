"""Turn memoization must conservatively invalidate uncertain metadata."""
import subprocess
from pathlib import Path
from tests.test_issue2768_workspace_links import _extract_function

ROOT = Path(__file__).resolve().parents[1]


def test_turn_memo_tracks_unanchored_tools_and_rejects_partial_turns():
    fn = _extract_function((ROOT/'static/ui.js').read_text(), '_settledTurnMemoInput')
    script = """
const assert=require('node:assert/strict');
const window={};const chatActivityMode=()=> 'transparent_stream';
const S={session:{session_id:'test',workspace:'/example'},toolCalls:[],messages:[
 {role:'user',content:'first'}, {role:'assistant',content:'answer'},
 {role:'user',content:'second'}, {role:'assistant',content:'latest'}]};
const visible=()=>S.messages.map((m,rawIdx)=>({m,rawIdx}));
""" + fn + """
const snapshot=()=>_settledTurnMemoInput(1,visible());
const empty=snapshot().signature;
for(const idx of [undefined,null,-1,'',NaN]){
 S.toolCalls=[{name:'read_file',assistant_msg_idx:idx,snippet:'changed'}];
 assert.notEqual(snapshot().signature,empty,'uncertain tool anchor must invalidate');
}
S.toolCalls=[];
assert.equal(_settledTurnMemoInput(3,visible()),null,'latest turn is never memoized');
for(const flag of ['_live','_partial','_pending']){
 S.messages[1][flag]=true;assert.equal(snapshot(),null);delete S.messages[1][flag];
}
S.messages[1].content='edited';assert.notEqual(snapshot().signature,empty);
S.messages[1].content='answer';
S.session.workspace='/other';assert.notEqual(snapshot().signature,empty);
S.session.workspace='/example';
window._showThinking=false;assert.notEqual(snapshot().signature,empty);
S.messages[1]={role:'assistant',content:'answer'};S.toolCalls=[];
S.messages.splice(2,0,{role:'assistant',content:'wakeup',_source:'process_wakeup'},{role:'assistant',content:'after wakeup'});
assert.equal(snapshot(),null,'wakeup echo-comparison runs retain ordinary rendering');
assert.equal(_settledTurnMemoInput(3,visible()),null,'turn after wakeup also retains ordinary rendering');
S.messages.splice(2,2);
S.messages[1]._liveSegmentSeq=9;
assert.equal(snapshot(),null,'routed legacy segments retain ordinary rendering');
delete S.messages[1]._liveSegmentSeq;
S.toolCalls=[{assistant_msg_idx:1,activitySegmentSeq:9,name:'read_file'}];
assert.equal(snapshot(),null,'cross-segment tool routing retains ordinary rendering');
console.log('ok');
"""
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,cwd=ROOT)
    assert result.returncode == 0,result.stderr


def test_turn_memo_invalidates_at_local_day_boundary():
    fn = _extract_function((ROOT/'static/ui.js').read_text(), '_settledTurnMemoInput')
    script = """
const assert=require('node:assert/strict');
const NativeDate=Date;
let now=new NativeDate(2026,0,1,23,59).getTime();
global.Date=class extends NativeDate {constructor(...args){super(...(args.length?args:[now]));}};
const window={};const chatActivityMode=()=> 'compact_worklog';
const S={session:{session_id:'test'},toolCalls:[],messages:[
 {role:'user',content:'first'}, {role:'assistant',content:'answer',_ts:now/1000},
 {role:'user',content:'second'}]};
const visible=S.messages.map((m,rawIdx)=>({m,rawIdx}));
""" + fn + """
const before=_settledTurnMemoInput(1,visible).signature;
now=new NativeDate(2026,0,2,0,1).getTime();
assert.notEqual(_settledTurnMemoInput(1,visible).signature,before,'relative footer date must refresh after midnight');
"""
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,cwd=ROOT)
    assert result.returncode == 0,result.stderr
