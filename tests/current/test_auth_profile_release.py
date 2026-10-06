"""Release must clear stale bookkeeping without touching an active profile."""
from types import SimpleNamespace
from unittest.mock import Mock
import engine.net as net
import main
from tests.current.test_auth_handoff_lifecycle import app_for, done


def clock(monkeypatch):
    ticks = [0.0]
    monkeypatch.setattr(net.time, 'monotonic', lambda: ticks[0])
    monkeypatch.setattr(net.time, 'sleep', lambda n: ticks.__setitem__(0, ticks[0] + 0.5))


def test_stale_owner_marker_does_not_strand_completed_login(tmp_path, monkeypatch):
    marker = tmp_path / 'tekzite-helper.pid'
    marker.write_text('123')
    (tmp_path / 'SingletonCookie').write_text('stale')
    monkeypatch.setattr(net, '_profile_chromium_pids', lambda _: [])
    monkeypatch.setattr(net, '_pid_is_alive', lambda _: False)
    clock(monkeypatch)
    handle = {'profile': str(tmp_path), 'browser_pids': [123],
              'process': SimpleNamespace(poll=lambda: 0),
              'return_url': 'https://github.com/',
              'google_auth_success_signal': ('return',),
              'auth_provider_independent_success': True,
              'auth_return_url_seen': 'https://github.com/'}
    assert net.wait_for_standalone_auth_chromium_release(handle, timeout=1.0)
    assert not marker.exists()
    assert not (tmp_path / 'SingletonCookie').exists()
    app = app_for(handle)
    app._google_auth_release_future = done(True)
    app._poll_google_auth_profile_release()
    assert app.root.after.call_args.args == (80, app._finish_google_auth_handoff, True)


def test_release_never_clears_markers_while_tracked_process_is_alive(tmp_path, monkeypatch):
    marker = tmp_path / 'tekzite-helper.pid'; marker.write_text('123')
    lock = tmp_path / 'SingletonCookie'; lock.write_text('live')
    monkeypatch.setattr(net, '_profile_chromium_pids', lambda _: [])
    monkeypatch.setattr(net, '_pid_is_alive', lambda _: True)
    clock(monkeypatch)
    handle = {'profile': str(tmp_path), 'browser_pids': [123]}
    assert not net.wait_for_standalone_auth_chromium_release(handle, timeout=1.0)
    assert marker.exists()
    assert lock.exists()


def test_release_never_clears_markers_of_adopted_profile_owner(tmp_path, monkeypatch):
    marker = tmp_path / 'tekzite-helper.pid'; marker.write_text('456')
    monkeypatch.setattr(net, '_profile_chromium_pids', lambda _: [456])
    monkeypatch.setattr(net, '_pid_is_alive', lambda _: True)
    clock(monkeypatch)
    assert not net.wait_for_standalone_auth_chromium_release({'profile': str(tmp_path)}, timeout=1.0)
    assert marker.exists()
