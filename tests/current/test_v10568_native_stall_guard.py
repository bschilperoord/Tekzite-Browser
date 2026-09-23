from pathlib import Path
import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version_10568():
    assert main.BROWSER_VERSION == "10.5.73"


def test_hot_navigation_clears_stale_cold_frame_diagnostics():
    start = NET.index("    if attach_native:")
    start = NET.index("        if hot_native_navigation:", start)
    end = NET.index("            return session", start) + len("            return session")
    block = NET[start:end]
    assert '"attached_frame_visual"' in block
    assert '"attached_frame_text_len"' in block
    assert '"first_frame_text_len"' in block
    assert 'session["hot_navigation_surface_probe_suppressed"] = True' in block


def test_hot_native_navigation_skips_fixed_visible_surface_probe():
    start = MAIN.index("    def _poll_embedded_navigation(")
    end = MAIN.index("    def _navigate_embedded(", start)
    block = MAIN[start:end]
    assert "if not hot_native_reuse:" in block
    assert "self.root.after(260, self._probe_visible_embedded_surface" in block
    assert "recrop_delays = (260, 700, 1250) if hot_native_reuse" in block


def test_native_stall_requires_completed_page_and_two_blank_confirmations():
    start = MAIN.index("    def _probe_visible_embedded_surface(")
    end = MAIN.index("    def _enforce_visible_surface_software_fallback", start)
    block = MAIN[start:end]
    assert 'if bool(tab.get("loading")):' in block
    assert 'tab["native_surface_blank_confirmations"] = 0' in block
    assert 'confirmations = int(tab.get("native_surface_blank_confirmations") or 0) + 1' in block
    assert "if confirmations < 2:" in block
    assert "_schedule_embedded_surface_wake" not in block
    assert "holding DComp geometry stable" in block


def test_hot_reuse_flag_is_reset_for_every_navigation():
    start = NET.index("def open_embedded_chromium(")
    end = NET.index("    hot_native_navigation = bool(", start)
    block = NET[start:end]
    assert 'session["hot_navigation_reused_native_surface"] = False' in block
    assert 'session["hot_navigation_surface_probe_suppressed"] = False' in block
