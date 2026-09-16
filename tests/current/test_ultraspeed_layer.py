import json
from pathlib import Path

import tekzite_network as core
import tekzite_network_fast as fast


def test_fast_host_matchers_preserve_known_blocking_semantics():
    assert fast._is_tracker_host("www.google-analytics.com")
    assert fast._is_browser_telemetry_host("vortex.data.microsoft.com")


def test_adblock_policy_live_updates_without_reparsing_unchanged_policy(tmp_path, monkeypatch):
    policy = tmp_path / "adblock-policy.json"
    policy.write_text(json.dumps({"enabled": True}), encoding="utf-8")

    monkeypatch.setattr(core, "ADBLOCK_POLICY", str(policy))
    monkeypatch.setattr(core, "ADBLOCK_ENABLED", True)
    fast._reset_fast_caches_for_tests()

    assert fast._is_ad_host("pagead2.googlesyndication.com")

    policy.write_text(json.dumps({"enabled": False}), encoding="utf-8")

    # Existing Tekzite behavior: policy changes are visible immediately.
    assert not fast._is_ad_host("pagead2.googlesyndication.com")


def test_privacy_stats_are_coalesced(monkeypatch):
    calls = []

    def fake_write():
        calls.append(1)

    monkeypatch.setattr(core, "_write_privacy_stats", fake_write)
    monkeypatch.setattr(fast, "STATS_FLUSH_SECONDS", 60.0)
    fast._reset_fast_caches_for_tests()

    before = int(core._PRIVACY_STATS.get("ads_blocked", 0) or 0)
    for _ in range(25):
        fast._privacy_stat("ads_blocked")

    # Hot request threads do not synchronously hit the filesystem.
    assert calls == []
    assert int(core._PRIVACY_STATS["ads_blocked"]) == before + 25

    fast._flush_privacy_stats()
    assert calls == [1]

    fast._reset_fast_caches_for_tests()


def test_ultraspeed_launcher_applies_tuning_before_main_import():
    source = Path("ultraspeed_launcher.py").read_text(encoding="utf-8")
    assert source.index("apply_ultraspeed()") < source.index("from main import BrowserApp")

def test_ultraspeed_launcher_closes_chromium_before_network_helper():
    source = Path("ultraspeed_launcher.py").read_text(encoding="utf-8")
    assert "def _shutdown_onefile_children" in source
    assert "net.close_embedded_chromium(clear_profile=False)" in source
    assert "net._profile_chromium_pids(profile)" in source
    assert "net._terminate_profile_chromium_processes(profile)" in source
    assert "net._stop_network_engine()" in source
    assert source.index("net.close_embedded_chromium(clear_profile=False)") < source.index("net._stop_network_engine()")

def test_network_helper_shutdown_targets_real_listener_pid():
    source = Path("engine/net.py").read_text(encoding="utf-8")
    block = source[
        source.index("def _stop_network_engine_unlocked():"):
        source.index("atexit.register(_stop_network_engine)")
    ]
    assert "_listener_pid_for_port(int(state_port))" in block
    assert "independently of proc.poll()" in block
    assert '["taskkill", "/PID", str(pid), "/T", "/F"]' in block
    assert "Final exact-port fallback" in block

