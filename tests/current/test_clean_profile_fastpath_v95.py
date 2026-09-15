from pathlib import Path

NET = Path("engine/net.py").read_text(encoding="utf-8")


def test_clean_profile_skips_expensive_cim_scan():
    assert "def _profile_recovery_needed" in NET
    assert "recovery_needed = bool(attempt > 1 or _profile_recovery_needed(profile))" in NET
    assert '"clean_profile_fast_path"' in NET


def test_window_discovery_poll_is_tight():
    block = NET[NET.index("def _find_chromium_window"):NET.index("def _hide_chromium_session_window") ]
    assert "time.sleep(0.005)" in block
    assert "time.sleep(0.10)" not in block


def test_launch_phase_timing_is_recorded():
    for marker in ("profile_recovery_ms", "process_spawn_ms", "devtools_ready_ms", "window_discovery_ms"):
        assert marker in NET
