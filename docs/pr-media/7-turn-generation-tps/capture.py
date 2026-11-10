import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ARTIFACT = Path(__file__).resolve().parent
report = {}
port = int(os.environ.get("WEBUI_PORT", "59901"))
prefix = os.environ.get("CAPTURE_PREFIX", "composer-tps")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
    if page.evaluate("typeof closeMobileSidebar==='function'"):
        page.evaluate("closeMobileSidebar()")
    if prefix == "composer-tps":
        page.wait_for_selector("#composerTps", state="visible")
        page.evaluate("S.messages=[{role:'user',content:'tool run'},{role:'assistant',content:'running tool',tool_calls:[{id:'verification',name:'terminal'}]},{role:'assistant',content:'verification complete',_turnTps:8400,_turnGenerationTps:120,_turnGenerationRecorded:true}]; renderMessages();")
        report['plain_local_command'] = page.evaluate("S.messages.push({role:'assistant',content:'Local title command'});renderMessages();document.querySelector('#composerTps').textContent")
        report['status_card'] = page.evaluate("S.messages.push({role:'assistant',content:'',_ephemeral:true,_statusCard:{title:'Status'}});renderMessages();document.querySelector('#composerTps').textContent")
        assert report['plain_local_command'] == '120 tps', report
        assert report['status_card'] == '120 tps', report
        page.evaluate("S.messages=S.messages.slice(0,-2);renderMessages();")
    page.screenshot(path=str(ARTIFACT / f"{prefix}-desktop.png"), full_page=False)
    report["desktop"] = page.evaluate("({tps:document.querySelector('#composerTps')?.textContent||'absent',display:document.querySelector('#composerTps')?getComputedStyle(document.querySelector('#composerTps')).display:'absent',nextSibling:document.querySelector('#composerTps')?.nextElementSibling?.id||'absent'})")
    if prefix == "composer-tps":
        assert report["desktop"] == {"tps": "120 tps", "display": "block", "nextSibling": "ctxIndicatorWrap"}, report["desktop"]
    else:
        assert report["desktop"] == {"tps": "absent", "display": "absent", "nextSibling": "absent"}, report["desktop"]
    page.set_viewport_size({"width": 390, "height": 844})
    if page.evaluate("typeof closeMobileSidebar==='function'"):
        page.evaluate("closeMobileSidebar()")
    page.screenshot(path=str(ARTIFACT / f"{prefix}-mobile.png"), full_page=False, animations="disabled")
    report["mobile"] = page.evaluate("({display:document.querySelector('#composerTps')?getComputedStyle(document.querySelector('#composerTps')).display:'absent',scrollWidth:document.documentElement.scrollWidth,innerWidth:innerWidth})")
    expected_mobile = "none" if prefix == "composer-tps" else "absent"
    assert report["mobile"]["display"] == expected_mobile, report["mobile"]
    assert report["mobile"]["scrollWidth"] <= report["mobile"]["innerWidth"], report["mobile"]
    browser.close()
print(json.dumps(report, indent=2))
