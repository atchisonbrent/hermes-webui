"""Execute production polling code with a stalled transport and fake clock."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_background_poll_is_single_flight_and_timeout_is_quiet():
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    panels = (ROOT / "static/panels.js").read_text()
    polling = panels[panels.index("let _cronPollSince="):panels.index("function updateCronBadge(){")]
    workspace = (ROOT / "static/workspace.js").read_text()
    api = workspace[:workspace.index("function recordClientSSEError(")]
    script = r'''
const assert = require('node:assert/strict');
let tick, requests=0, toasts=0;
const timers=[];
global.document={hidden:false,baseURI:'http://localhost/'};
global.window={addEventListener(){}};
global.setInterval=fn=>{tick=fn; return 1;};
global.setTimeout=(fn,ms)=>{assert.equal(ms,30000,'unexpected retry timer');timers.push(fn);return timers.length;};
global.clearTimeout=()=>{};
global.fetch=()=>{requests++; return new Promise(()=>{});};
global.showToast=()=>{toasts++;};
global.updateCronBadge=()=>{};
''' + api + polling + r'''
(async()=>{
 startCronPolling();
 const first=tick();
 const overlapping=tick();
 assert.equal(requests,1,'overlapping cron poll queued another request');
 await overlapping;
 timers.shift()(); await first;
 assert.equal(toasts,0,'background poll displayed timeout toast');
 const next=tick();
 assert.equal(requests,2,'failure did not release in-flight guard');
 timers.shift()(); await next;
 assert.equal(toasts,0,'second timeout displayed a toast');
 global.fetch=async()=>{requests++;throw new TypeError('network failed');};
 await tick();
 assert.equal(requests,3,'network failure retried');
 timers.length=0;
 global.fetch=async()=>{requests++;return {ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>({completions:[]})};};
 await tick(); await tick();
 assert.equal(requests,5,'success did not release guard');
 let resolveFetch;
 global.fetch=()=>{requests++;return new Promise(resolve=>{resolveFetch=resolve;});};
 const stale=tick(); _cronPollGeneration++;
 resolveFetch({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>({completions:[]})});
 await stale;
 const afterFence=tick();
 assert.equal(requests,7,'profile fence did not release guard');
 resolveFetch({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>({completions:[]})});
 await afterFence;
 console.log('poll lifecycle verified');
})().catch(e=>{console.error(e);process.exit(1);});
'''
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
