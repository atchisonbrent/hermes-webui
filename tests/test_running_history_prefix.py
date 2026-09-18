"""Raw scroll-index shifts follow retained prefix identity, not tail growth."""
import json
import subprocess
from pathlib import Path
from tests.test_cross_session_message_load_isolation import _extract_function


def test_running_prefix_ignores_live_tail_growth():
    source=(Path(__file__).resolve().parents[1]/'static/sessions.js').read_text()
    helper=_extract_function(source,'_prependedRunningHistory')
    start=source.index('    const unreconciledMessages=nextMessages;')
    end=source.index('    S.messages = nextMessages;',start)
    script=helper+'''
const user={role:'user',content:'prompt',_active_turn_boundary_stream:'run'};
const currentMsgs=[user,{role:'assistant',_live:true,content:'old'}];
const olderMsgs=[{role:'user',content:'history'},{role:'assistant',content:'partial'}];
const responseSession={};
let nextMessages=[...olderMsgs,...currentMsgs];
function _reconcileRunningMessageWindow(){return [olderMsgs[0],{...user},currentMsgs[1],{role:'assistant',_live:true,content:'new'}];}
'''+source[start:end]+'''
console.log(JSON.stringify(prependedMessages.map(m=>m.content)));
'''
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==['history']
