from pathlib import Path

from engine import net


ROOT = Path(__file__).resolve().parents[2]
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_permission_bridge_installs_before_real_navigation_only():
    nav = NET[NET.index("def navigate_embedded_chromium"):NET.index("def _windows_descendant_pids")]
    create = NET[NET.index("def create_embedded_chromium_target"):NET.index("def activate_embedded_chromium_target")]
    assert "install_embedded_chromium_permission_bridge" in nav
    assert "install_embedded_chromium_permission_bridge" not in create
    assert "Page.addScriptToEvaluateOnNewDocument" in NET
    assert "permission-bridge/install" in NET


def test_permission_bridge_covers_common_permission_apis():
    for needle in (
        "Notification.requestPermission",
        "getUserMedia",
        "getCurrentPosition",
        "watchPosition",
        "navigator.clipboard",
        "requestMIDIAccess",
        "DeviceMotionEvent",
        "DeviceOrientationEvent",
    ):
        assert needle in NET


def test_permission_poll_sanitizes_page_rows(monkeypatch):
    monkeypatch.setattr(net, "_CHROMIUM_SESSION", {"port": 9222})

    def fake_call(*args, **kwargs):
        return {
            "result": {
                "value": [
                    {
                        "id": 7,
                        "kind": "camera+microphone",
                        "origin": "https://example.test",
                        "permissions": ["camera", "microphone", "bogus", "camera"],
                    }
                ]
            }
        }

    monkeypatch.setattr(net, "_persistent_page_cdp_call", fake_call)
    assert net.poll_embedded_chromium_permission_requests("target-1") == [
        {
            "id": 7,
            "kind": "camera+microphone",
            "origin": "https://example.test",
            "permissions": ["camera", "microphone"],
            "target_id": "target-1",
        }
    ]


def test_tk_prompt_has_once_and_remember_choices():
    assert "_schedule_permission_prompt_poll(450)" in FEATURES
    assert "Tekzite Site Permission" in FEATURES
    assert "Allow once" in FEATURES
    assert "Always allow" in FEATURES
    assert "Block once" in FEATURES
    assert "Always block" in FEATURES
    assert "Default Tekzite policy is Ask in Tk." in FEATURES


def test_permission_manager_defaults_missing_rules_to_ask():
    apply_block = FEATURES[
        FEATURES.index("def _apply_permissions_for_tab"):
        FEATURES.index("def _permission_pref_key")
    ]
    assert "rule.get(key) or 'ask'" in apply_block
    assert "rule.get(key) or 'block'" not in apply_block
