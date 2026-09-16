"""Serialized, background-only calls to the bundled local extension."""
import json
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
        session = session or net._EDGE_SESSION
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
