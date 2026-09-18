"""Exercise the production cleanup callback with a deterministic timer queue."""
import json
import subprocess
from pathlib import Path


def test_registry_cleanup_tracks_live_transport_not_age():
    source = (Path(__file__).resolve().parents[1] / 'static/messages.js').read_text()
    start = source.index('  function _scheduleAnchorRegistryCleanup(')
    end = source.index('\n  // Backstop:', start)
    result = subprocess.run(['node', '-e', '''
const assert=require('node:assert/strict');
const timers=[];
const setTimeout=(fn,delay)=>{timers.push({fn,delay});};
const streamId='run',activeSid='session';
const _anchorRegistry={},_anchorRegistryMap=new Map([[streamId,_anchorRegistry]]);
const LIVE_STREAMS={[activeSid]:{streamId,source:{readyState:1}}};
''' + source[start:end] + '''
_scheduleAnchorRegistryCleanup();
for(let i=0;i<3;i++){
  assert.equal(timers[0].delay,600000);
  timers.shift().fn();
  assert.equal(_anchorRegistryMap.get(streamId),_anchorRegistry,'active registry expired');
  assert.equal(timers.length,1,'active cleanup must reschedule');
}
LIVE_STREAMS[activeSid].source.readyState=0;
timers.shift().fn();
assert.equal(_anchorRegistryMap.get(streamId),_anchorRegistry,'reconnecting registry expired');
LIVE_STREAMS[activeSid].source.readyState=2;
timers.shift().fn();
assert.equal(_anchorRegistryMap.has(streamId),false,'closed registry leaked');
assert.equal(timers.length,0);
_anchorRegistryMap.set(streamId,_anchorRegistry);
_scheduleAnchorRegistryCleanup(120000);
delete LIVE_STREAMS[activeSid];
timers.shift().fn();
assert.equal(_anchorRegistryMap.has(streamId),false,'external teardown leaked');
_anchorRegistryMap.set(streamId,_anchorRegistry);
_scheduleAnchorRegistryCleanup();
const replacement={};
_anchorRegistryMap.set(streamId,replacement);
timers.shift().fn();
assert.equal(_anchorRegistryMap.get(streamId),replacement,'old timer erased replacement');
assert.equal(timers.length,0);
console.log(JSON.stringify({ok:true}));
'''], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'ok': True}
