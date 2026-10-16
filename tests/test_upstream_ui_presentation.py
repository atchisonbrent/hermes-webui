"""Upstream-first presentation: public prose is not a fork-only disclosure."""
import json
import subprocess

from tests.test_issue2613_render_cache_signature import NODE, _collect_functions


def test_compact_mode_uses_upstream_visible_prose_boundary():
    script = _collect_functions(['_assistantMessageBelongsInWorklog']) + '''
const isCompactWorklogMode=()=>true;
const msgContent=m=>m.content||'';
const _isAssistantEmptyPlaceholderContent=()=>false;
const cases=[
  [{role:'assistant',content:'Checking the source.'}, {}, false],
  [{role:'assistant',content:'Finished.'}, {isTurnFinalAssistant:true}, false],
  [{role:'assistant',content:'',tool_calls:[{id:'tool-one'}]}, {}, true],
];
console.log(JSON.stringify(cases.map(([m,opts])=>
  _assistantMessageBelongsInWorklog(m,0,new Set(),m.content,opts))));
'''
    result = subprocess.run([NODE, '-e', script], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [False, False, True]
