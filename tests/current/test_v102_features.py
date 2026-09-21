from pathlib import Path
from unittest.mock import Mock
import json

import main
from browser_state import session_snapshot
from engine import net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
FEATURES = (ROOT / 'browser_features.py').read_text(encoding='utf-8')
EXT = (ROOT / 'chromium_zoom_extension' / 'features.js').read_text(encoding='utf-8')


def test_release_is_v1020():
    assert main.BROWSER_VERSION == '10.5.42'


def test_profile_slug_and_state_root_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setenv('TEKZITE_BROWSER_PROFILE', 'Music')
    assert main._profile_slug(' Music / bad? ') == 'Music-bad'
    assert main._preferences_path() == tmp_path / 'Tekzite Browser' / 'Profiles' / 'Music' / 'preferences.json'


def test_tab_group_is_preserved_in_session_snapshot():
    snap = session_snapshot([{'id': 4, 'url': 'https://example.test', 'title': 'Example', 'group': 'Research'}], 4)
    assert snap['tabs'][0]['group'] == 'Research'


def test_sleeping_tabs_are_real_target_release_and_wake_route():
    assert 'close_embedded_chromium_target(target_id)' in MAIN
    assert 'tab["sleeping"] = True' in MAIN
    assert 'tab["restore_pending"] = True' in MAIN
    assert 'self._wake_tab_if_needed(target)' in MAIN


def test_permissions_manager_uses_origin_scoped_browser_permission():
    source = Path(net.__file__).read_text(encoding='utf-8')
    assert 'def set_embedded_chromium_permission' in source
    assert "'Browser.setPermission'" in source
    assert "'origin': origin" in source
    assert 'Permissions Manager' in MAIN
    assert 'site_permissions' in FEATURES


def test_downloads_20_actions_are_present():
    for action in ('pause', 'resume', 'open', 'erase'):
        assert f'action === "{action}"' in EXT
    manifest = json.loads((ROOT / 'chromium_zoom_extension' / 'manifest.json').read_text(encoding='utf-8'))
    assert 'downloads.open' in manifest['permissions']


def test_management_panels_are_wired():
    for label in ('Tab Groups', 'Profiles', 'Task Manager', 'Diagnostics', 'Check for Updates'):
        assert label in MAIN


def test_crash_recovery_prompt_is_wired():
    assert 'Tekzite did not finish its previous shutdown cleanly' in MAIN
    assert 'session.get("clean_exit") is False' in MAIN


def test_download_prompt_launch_flag_is_opt_in():
    source = Path(net.__file__).read_text(encoding='utf-8')
    assert 'TEKZITE_DOWNLOAD_PROMPT' in source
    assert '--download-prompt-for-download' in source


def test_sleep_tab_releases_target_and_marks_restore(monkeypatch):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.active_tab_id = 1
    app._refresh_tab_strip = Mock()
    tab = {
        'id': 2, 'url': 'https://example.test', 'chromium_target_id': 'target-2',
        'loaded': True, 'loading': False, 'ready_state': 'complete', 'pinned': False,
    }
    closed = []
    monkeypatch.setattr(main, 'close_embedded_chromium_target', lambda target_id: closed.append(target_id))
    assert app._sleep_tab(tab) is True
    assert closed == ['target-2']
    assert tab['chromium_target_id'] is None
    assert tab['sleeping'] is True
    assert tab['restore_pending'] is True


def test_wake_tab_marks_reload_route():
    app = main.BrowserApp.__new__(main.BrowserApp)
    tab = {'url': 'https://example.test', 'sleeping': True}
    assert app._wake_tab_if_needed(tab) is True
    assert tab['sleeping'] is False
    assert tab['restore_pending'] is True


def test_permission_helper_uses_browser_set_permission(monkeypatch):
    session = {'port': 1234}
    calls = []
    monkeypatch.setattr(net, '_EDGE_SESSION', session)
    monkeypatch.setattr(net, '_browser_cdp_call', lambda sess, method, params=None, **kw: calls.append((method, params)) or {})
    assert net.set_embedded_chromium_permission('https://example.test', 'geolocation', 'denied') is True
    assert calls == [('Browser.setPermission', {'permission': {'name': 'geolocation'}, 'setting': 'denied', 'origin': 'https://example.test'})]

