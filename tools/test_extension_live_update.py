"""Smoke-test immediate unpacked-extension reload in a disposable Chromium profile.

Run: python tools/test_extension_live_update.py /path/to/chrome-for-testing
Requires a Chromium build supporting --load-extension in headless mode.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import features, net
import extension_updates as updates
from browser_state import write_json


def wait_worker_api(ws):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = net._cdp_call(ws, 'Runtime.evaluate', {
            'expression': 'typeof chrome !== "undefined" && !!chrome.storage && !!chrome.storage.local',
            'returnByValue': True,
        }, timeout=3)
        if result.get('result', {}).get('value') is True:
            return
        time.sleep(.1)
    raise RuntimeError('Extension worker API did not initialize: ' + str(result))


def run(executable):
    with tempfile.TemporaryDirectory(prefix='tekzite-live-update-') as directory:
        root = Path(directory)
        extension = root / 'extension'; extension.mkdir()
        old = {'name': 'Tekzite Update Smoke Test', 'manifest_version': 3, 'version': '1.0',
               'permissions': ['storage'], 'background': {'service_worker': 'worker.js'}}
        (extension / 'manifest.json').write_text(json.dumps(old))
        (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(() => {});')
        profile = root / 'profile'
        log = open(root / 'chrome.log', 'w')
        process = subprocess.Popen([str(executable), '--headless=new', '--no-sandbox', '--disable-gpu',
            '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0',
            f'--user-data-dir={profile}', f'--load-extension={extension}',
            '--disable-features=DisableLoadExtensionCommandLineSwitch', 'about:blank'], stdout=log, stderr=log)
        session = None
        try:
            deadline = time.monotonic() + 15
            while not (profile / 'DevToolsActivePort').exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Test Chromium did not start: ' + (root / 'chrome.log').read_text()[:1500])
                time.sleep(.05)
            port = int((profile / 'DevToolsActivePort').read_text().splitlines()[0])
            session = {'port': port}
            deadline = time.monotonic() + 10
            worker = None
            while time.monotonic() < deadline:
                try:
                    targets = net._devtools_json(port, '/json/list', timeout=3)
                except OSError:
                    time.sleep(.1)
                    continue
                worker = next((t for t in targets if t.get('type') == 'service_worker' and t.get('url', '').endswith('/worker.js')), None)
                if worker:
                    break
                time.sleep(.05)
            if not worker:
                raise RuntimeError('Test extension did not load')
            identity = worker['url'].split('/')[2]
            ws = net._open_devtools_websocket(worker['webSocketDebuggerUrl'])
            try:
                wait_worker_api(ws)
                result = net._cdp_call(ws, 'Runtime.evaluate', {'expression': 'chrome.storage.local.set({sentinel:"preserved"})', 'awaitPromise': True, 'returnByValue': True})
                if result.get('exceptionDetails'):
                    raise RuntimeError('Could not initialize test extension storage: ' + str(result))
            finally:
                ws.close()
            cache = updates.cache_dir(root / 'state')
            stage = cache / updates.token(extension); stage.mkdir(parents=True)
            new = dict(old, version='2.0')
            (stage / 'manifest.json').write_text(json.dumps(new))
            (stage / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(() => {});')
            write_json(cache / (updates.token(extension) + '.ready.json'), {'base': '1.0', 'version': '2.0'})
            entries = [{'path': str(extension), 'enabled': True}]
            before = {t['id'] for t in net._devtools_json(port, '/json/list') if t['type'] == 'page'}
            with features.extension_reloader(session) as reload_extension:
                results = updates.apply_pending(entries, root / 'state', reload_extension=reload_extension)
            if results[0]['state'] != 'updated':
                raise RuntimeError(str(results))
            after = {t['id'] for t in net._devtools_json(port, '/json/list') if t['type'] == 'page'}
            assert before == after, 'Hidden extension manager target was not cleaned up'
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    targets = net._devtools_json(port, '/json/list', timeout=3)
                except OSError:
                    time.sleep(.1)
                    continue
                worker = next((t for t in targets if t.get('url') == f'chrome-extension://{identity}/worker.js'), None)
                if worker:
                    break
                time.sleep(.05)
            ws = net._open_devtools_websocket(worker['webSocketDebuggerUrl'])
            try:
                wait_worker_api(ws)
                info = net._cdp_call(ws, 'Runtime.evaluate', {'expression': '(async()=>({version:chrome.runtime.getManifest().version,sentinel:(await chrome.storage.local.get("sentinel")).sentinel}))()', 'awaitPromise': True, 'returnByValue': True})['result']['value']
                assert info == {'version': '2.0', 'sentinel': 'preserved'}, info
            finally:
                ws.close()
            print(json.dumps({'immediate_update': True, 'runtime_version': info['version'], 'settings_preserved': True, 'extension_id_preserved': True, 'browser_restart_required': False, 'hidden_target_cleaned_up': True}))
        finally:
            if session:
                try:
                    net._browser_cdp_call(session, 'Browser.close', timeout=2)
                except Exception:
                    pass
                net._close_persistent_browser_cdp_channel(session)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
            log.close()


if __name__ == '__main__':
    run(sys.argv[1])
