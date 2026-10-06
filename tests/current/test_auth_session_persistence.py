"""Profile/launch configuration regressions; not a live provider login test."""
import json
from types import SimpleNamespace
import pytest
import engine.net as net

@pytest.mark.parametrize('directory', ['Default', 'Profile 2'])
def test_restore_preserves_profile_data_and_cookie_database(tmp_path, directory):
    profile = tmp_path / directory
    profile.mkdir()
    (tmp_path / 'Local State').write_text(json.dumps({'profile': {'last_used': directory}}))
    preferences = {'session': {'restore_on_startup': 5, 'startup_urls': ['https://example.test/']},
                   'profile': {'exit_type': 'Normal'}, 'unrelated': {'keep': True}}
    (profile / 'Preferences').write_text(json.dumps(preferences))
    (profile / 'Cookies').write_bytes(b'opaque-cookie-db')
    assert net._chromium_profile_directory(tmp_path) == directory
    net._apply_privacy_profile_preferences(tmp_path)
    net._enable_chromium_session_restore(tmp_path, directory)
    result = json.loads((profile / 'Preferences').read_text())
    assert result['session']['restore_on_startup'] == 1
    assert result['session']['startup_urls'] == preferences['session']['startup_urls']
    assert result['profile']['exit_type'] == 'Normal'
    assert result['unrelated'] == {'keep': True}
    assert (profile / 'Cookies').read_bytes() == b'opaque-cookie-db'
    if directory != 'Default':
        assert not (tmp_path / 'Default').exists()

@pytest.mark.parametrize('name', ['../outside', '/outside', 'Profile 2/../outside', 'Profile missing'])
def test_profile_selection_rejects_invalid_directory(tmp_path, name):
    (tmp_path / 'Local State').write_text(json.dumps({'profile': {'last_used': name}}))
    assert net._chromium_profile_directory(tmp_path) == 'Default'

class CapturedLaunch(BaseException):
    def __init__(self, command): self.command = command

class WindowsOS:
    name = 'nt'
    def __getattr__(self, name): return getattr(__import__('os'), name)

@pytest.mark.parametrize('standalone', [False, True])
def test_both_launchers_use_same_selected_profile_and_restore_cookies(tmp_path, monkeypatch, standalone):
    directory = 'Profile 2'
    (tmp_path / directory).mkdir()
    (tmp_path / 'Local State').write_text(json.dumps({'profile': {'last_used': directory}}))
    executable = tmp_path / 'chromium.exe'; executable.write_bytes(b'fake')
    monkeypatch.setattr(net, '_CHROMIUM_SESSION', None)
    monkeypatch.setattr(net, '_persistent_chromium_profile_dir', lambda: str(tmp_path))
    monkeypatch.setattr(net, '_chromium_candidates', lambda: [str(executable)])
    monkeypatch.setattr(net, '_profile_recovery_needed', lambda _: False)
    monkeypatch.setattr(net, '_clear_devtools_active_port', lambda _: None)
    monkeypatch.setattr(net, '_chromium_extension_dirs', lambda: [])
    monkeypatch.setattr(net, 'ensure_network_engine', lambda: {'proxy_url': 'http://127.0.0.1:1234'})
    monkeypatch.setattr(net, '_free_loopback_port', lambda: 12345)
    def capture(command, **kwargs): raise CapturedLaunch(command)
    monkeypatch.setattr(net.subprocess, 'Popen', capture)
    if standalone:
        monkeypatch.setattr(net, 'os', WindowsOS())
        monkeypatch.setattr(net, '_CHROMIUM_SESSION', {'profile': str(tmp_path), 'profile_directory': directory,
                                                    'executable': str(executable)})
        monkeypatch.setattr(net, '_close_embedded_chromium_cleanly_for_auth_unlocked', lambda **_: True)
        monkeypatch.setattr(net, '_profile_chromium_pids', lambda _: [])
        monkeypatch.setattr(net, '_clear_chromium_profile_locks', lambda _: None)
        monkeypatch.setattr(net, '_mark_chromium_profile_exited_cleanly', lambda _: None)
        monkeypatch.setattr(net, '_snapshot_google_auth_cookie_state', lambda _: {})
        monkeypatch.setattr(net, '_snapshot_auth_cookie_state', lambda *_: {})
        monkeypatch.setattr(net, '_snapshot_chromium_latest_visit', lambda *_: None)
        monkeypatch.setattr(net, '_standalone_auth_window_geometry', lambda: (0, 0, 1000, 800))
    with pytest.raises(CapturedLaunch) as captured:
        if standalone:
            net.start_standalone_auth_chromium('https://login.microsoftonline.com/', 'https://outlook.live.com/mail/')
        else:
            net._start_persistent_chromium_session_unlocked()
    command = captured.value.command
    assert f'--user-data-dir={tmp_path}' in command
    assert '--profile-directory=Profile 2' in command
    assert json.loads((tmp_path / directory / 'Preferences').read_text())['session']['restore_on_startup'] == 1
    assert not any(flag.startswith('--incognito') for flag in command)
    if standalone:
        assert '--new-window' not in command
