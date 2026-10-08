"""Serialized, background-only calls to the bundled local extension."""
import json
import contextlib
import os
from pathlib import Path
import threading
import time
from . import net

_LOCK = threading.RLock()
_CONFIG = {'enabled': True, 'sites': [], 'tracker_blocking': True, 'strip_referrer': True, 'https_first': True}


def set_config(enabled, sites, *, tracker_blocking=True, strip_referrer=True, https_first=True):
    global _CONFIG
    _CONFIG = {
        'enabled': bool(enabled),
        'sites': list(sites),
        'tracker_blocking': bool(tracker_blocking),
        'strip_referrer': bool(strip_referrer),
        'https_first': bool(https_first),
    }


def call(action, payload=None, session=None):
    with _LOCK:
        session = session or net._CHROMIUM_SESSION
        if not session:
            raise RuntimeError('Open a webpage first so Chromium can start.')
        channel = session.get('feature_channel')
        if channel is None:
            # Use the existing extension worker, never create another page/window.
            # An attached DevTools session keeps the worker alive on supported Chromium.
            worker_url = f'chrome-extension://{net.TEKZITE_ZOOM_EXTENSION_ID}/background.js'
            deadline = time.monotonic() + 8
            ws = None
            while time.monotonic() < deadline:
                targets = net._devtools_json(session['port'], '/json/list', timeout=1)
                worker = next((p for p in targets if p.get('type') == 'service_worker' and p.get('url') == worker_url), None)
                if worker and worker.get('webSocketDebuggerUrl'):
                    ws = net._open_devtools_websocket(worker['webSocketDebuggerUrl'], timeout=2)
                    break
                time.sleep(.03)
            if ws is None:
                raise RuntimeError('Local extension unavailable. Use Chromium with unpacked extension support.')
            try:
                # Service workers can be exposed by DevTools before running their script.
                net._cdp_call(ws, 'Runtime.enable', timeout=2)
                net._cdp_call(ws, 'Runtime.runIfWaitingForDebugger', timeout=2)
                probe = {'expression': 'typeof tekziteFeature === "function"', 'returnByValue': True}
                result = net._cdp_call(ws, 'Runtime.evaluate', probe, timeout=2)
                if not result.get('result', {}).get('value'):
                    # An old/still-starting worker may lack the new entry point.
                    # Install only our bundled function into the verified extension worker.
                    source = (net._zoom_extension_dir() / 'features.js').read_text(encoding='utf-8')
                    result = net._cdp_call(ws, 'Runtime.evaluate', {
                        'expression': source + '\n;typeof tekziteFeature === "function"',
                        'returnByValue': True}, timeout=2)
                    if result.get('exceptionDetails') or not result.get('result', {}).get('value'):
                        raise RuntimeError('Local extension service could not initialize; basic browsing remains available.')
                channel = {'ws': ws, 'target': worker['id']}
                session['feature_channel'] = channel
            except Exception:
                ws.close()
                raise
        expression = 'tekziteFeature(' + json.dumps(action) + ',' + json.dumps(payload or {}) + ')'
        try:
            result = net._cdp_call(channel['ws'], 'Runtime.evaluate', {
                'expression': expression, 'awaitPromise': True, 'returnByValue': True}, timeout=8)
        except Exception:
            session.pop('feature_channel', None)
            channel['ws'].close()
            raise
        if result.get('exceptionDetails'):
            detail = result['exceptionDetails']
            raise RuntimeError(detail.get('exception', {}).get('description') or detail.get('text') or 'Extension request failed')
        value = result.get('result', {}).get('value')
        if action == 'configure' and value is True:
            net._set_adblock_fallback(False)
            session['feature_services_ready'] = True
            session['feature_services_error'] = None
        return value


def configure(session=None):
    if call('configure', _CONFIG, session) is not True:
        raise RuntimeError('The local service did not confirm its configuration.')
    return True


def extension_inventory(session=None):
    value = call('extensionInventory', {}, session)
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        extension_id = str(item.get('id') or '').strip()
        if not extension_id:
            continue
        rows.append({
            'id': extension_id,
            'name': str(item.get('name') or ''),
            'shortName': str(item.get('shortName') or item.get('name') or ''),
            'version': str(item.get('version') or ''),
            'enabled': bool(item.get('enabled', True)),
            'installType': str(item.get('installType') or ''),
            'optionsUrl': str(item.get('optionsUrl') or ''),
            'homepageUrl': str(item.get('homepageUrl') or ''),
            'mayDisable': bool(item.get('mayDisable', True)),
            'icons': list(item.get('icons') or []),
        })
    return rows


@contextlib.contextmanager
def extension_reloader(session=None):
    """Reload exact unpacked paths through Chromium's hidden extension manager.

    Chromium's developerPrivate.reload rereads the manifest and works for MV2,
    MV3 and content-only extensions. No visible tab or browser window is opened.
    """
    session = session or net._CHROMIUM_SESSION
    if not session:
        raise RuntimeError('Chromium is not running')
    target_id = None
    ws = None
    try:
        target = net._browser_cdp_call(session, 'Target.createTarget', {
            'url': 'chrome://extensions/', 'background': True, 'hidden': True,
        }, timeout=5)
        target_id = target.get('targetId')
        if not target_id:
            raise RuntimeError('Hidden extension manager could not be created')
        deadline = time.monotonic() + 8
        inventory = None
        while time.monotonic() < deadline:
            pages = net._devtools_json(session['port'], '/json/list', timeout=1)
            page = next((p for p in pages if p.get('id') == target_id), None)
            if page and page.get('webSocketDebuggerUrl'):
                ws = net._open_devtools_websocket(page['webSocketDebuggerUrl'], timeout=2)
                result = net._cdp_call(ws, 'Runtime.evaluate', {
                    'expression': 'typeof chrome.developerPrivate !== "undefined" ? chrome.developerPrivate.getExtensionsInfo({includeDisabled:true,includeTerminated:true}) : null',
                    'awaitPromise': True, 'returnByValue': True,
                }, timeout=5)
                inventory = result.get('result', {}).get('value')
                if isinstance(inventory, list):
                    break
                ws.close(); ws = None
            time.sleep(.05)
        if not isinstance(inventory, list):
            raise RuntimeError('Chromium extension reload API is unavailable')
        def path_key(path):
            return os.path.normcase(str(Path(path).resolve()))
        paths = {path_key(row['path']): row for row in inventory
                 if row.get('path') and row.get('location') == 'UNPACKED'}
        def reload_extension(path, expected_version):
            row = paths.get(path_key(path))
            if not row or row.get('state') != 'ENABLED':
                raise RuntimeError('Extension is not enabled at its configured path')
            # Do not await Chromium's unpacked-load observer: some builds can
            # finish loading before it attaches. Verify the runtime separately.
            expression = 'chrome.developerPrivate.reload(%s,{failQuietly:true,populateErrorForUnpacked:false})' % json.dumps(row['id'])
            result = net._cdp_call(ws, 'Runtime.evaluate', {
                'expression': expression, 'awaitPromise': True, 'returnByValue': True,
            }, timeout=5)
            if result.get('exceptionDetails'):
                detail = result['exceptionDetails']
                raise RuntimeError(detail.get('exception', {}).get('description') or detail.get('text') or 'Extension reload failed')
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                result = net._cdp_call(ws, 'Runtime.evaluate', {
                    'expression': 'chrome.developerPrivate.getExtensionInfo(%s)' % json.dumps(row['id']),
                    'awaitPromise': True, 'returnByValue': True,
                }, timeout=3)
                info = result.get('result', {}).get('value') or {}
                if info.get('id') == row['id'] and info.get('version') == expected_version and info.get('state') == 'ENABLED':
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Reloaded extension did not confirm the expected version: ' + str(info))
            return True
        yield reload_extension
    finally:
        if ws is not None:
            ws.close()
        if target_id:
            try:
                net._browser_cdp_call(session, 'Target.closeTarget', {'targetId': target_id}, timeout=2)
            except Exception:
                pass


def privacy_stats(session=None):
    value = call('privacyStats', {}, session)
    if not isinstance(value, dict):
        return {'ads_blocked': 0, 'trackers_blocked': 0}
    return {
        'ads_blocked': max(0, int(value.get('ads_blocked', 0) or 0)),
        'trackers_blocked': max(0, int(value.get('trackers_blocked', 0) or 0)),
    }


def initialize_optional(session):
    """Never promote an optional-service failure into a browser launch failure."""
    try:
        configure(session)
        return True
    except Exception as exc:
        session['feature_services_ready'] = False
        session['feature_services_error'] = f'{type(exc).__name__}: {exc}'
        try:
            net._set_adblock_fallback(_CONFIG['enabled'])
        except Exception as policy_error:
            session['feature_services_error'] += f'; fallback policy: {policy_error}'
        return False
