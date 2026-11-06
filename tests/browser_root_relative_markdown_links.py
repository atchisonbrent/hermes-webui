#!/usr/bin/env python3
"""Render root-relative links in a real isolated page; no model or file access."""
import os
from pathlib import Path
import tempfile
import time
from playwright.sync_api import sync_playwright
from browser_conversation_lifecycle import _start_webui_server, _terminate_process

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='markdown-links-') as temp:
        env = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'SYSTEMROOT') if k in os.environ}
        env.update(HOME=temp, HERMES_HOME=temp, HERMES_BASE_HOME=temp,
                   HERMES_CONFIG_PATH=temp+'/config.yaml', HERMES_WEBUI_STATE_DIR=temp+'/webui',
                   HERMES_WEBUI_HOST='127.0.0.1', HERMES_WEBUI_SKIP_ONBOARDING='1',
                   HERMES_WEBUI_AGENT_DIR=temp+'/no-agent')
        proc, log, _, base = _start_webui_server(ROOT, env, Path(temp))
        try:
            with sync_playwright() as pw:
                for engine in ('chromium', 'webkit'):
                    browser = getattr(pw, engine).launch()
                    try:
                        for width in (1280, 390):
                            page = browser.new_page(viewport={'width':width, 'height':844})
                            errors=[]
                            page.on('pageerror', lambda e, errors=errors: errors.append(str(e)))
                            page.goto(base, wait_until='load')
                            deadline=time.monotonic()+30
                            while not page.evaluate("typeof renderMd==='function' && S._bootReady"):
                                assert time.monotonic()<deadline, 'boot timeout'
                                page.wait_for_timeout(50)
                            result=page.evaluate(r'''()=>{
                              const area=document.createElement('div');
                              area.id='link-proof';
                              area.innerHTML=renderMd('[**EPUB**](/api/file/raw?path=books%2Fstory.epub&session_id=fixture)');
                              document.querySelector('#msgInner').replaceChildren(area);
                              const a=area.querySelector('a');
                              if(!a)throw new Error('missing link');
                              if(new URL(a.href).origin!==location.origin)throw new Error('changed origin');
                              if(a.getAttribute('href')!=='/api/file/raw?path=books%2Fstory.epub&session_id=fixture')throw new Error('changed destination');
                              const unsafe=document.createElement('div');
                              unsafe.innerHTML=renderMd('<a class="session-link" href="/api/file/raw?path=x">not session navigation</a>');
                              if(unsafe.querySelector('a[href]'))throw new Error('unsafe application action');
                              return {link:true, applicationActionRejected:true};
                            }''')
                            output=os.environ.get('SCREENSHOT_DIR')
                            if output:
                                Path(output).mkdir(parents=True,exist_ok=True)
                                page.screenshot(path=str(Path(output)/f'links-{engine}-{width}.png'))
                            assert not errors,errors
                            print(engine,width,result,flush=True)
                            page.close()
                    finally:
                        browser.close()
        finally:
            _terminate_process(proc)
            log.close()


if __name__=='__main__':
    main()
