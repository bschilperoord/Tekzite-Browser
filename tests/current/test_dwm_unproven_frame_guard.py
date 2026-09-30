from pathlib import Path
import inspect

import main
from engine import net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_native_frame_gate_records_failure_instead_of_implying_readiness():
    block = NET[NET.index("def open_embedded_chromium"):NET.index("def record_embedded_native_recovery")]
    assert 'session["native_frame_gate_ready"] = bool(attached_ready)' in block
    assert 'session["native_frame_gate_deferred"] = not bool(attached_ready)' in block


def test_failed_native_frame_gate_is_deferred_before_dwm_reveal():
    block = inspect.getsource(main.BrowserApp._poll_embedded_navigation)
    assert "native_frame_ready = bool(" in block
    assert 'session.get("native_frame_gate_ready")' in block
    assert 'tab["presentation"] = "native-wait"' in block
    assert "self._defer_native_dwm_reveal(generation, target_id, url)" in block


def test_deferred_reveal_keeps_raw_dwm_hidden_until_retry_succeeds():
    block = inspect.getsource(main.BrowserApp._defer_native_dwm_reveal)
    assert block.index("self._show_native_canvas()") < block.index("wait_for_embedded_chromium_native_frame")
    assert 'if ready:' in block
    ready = block[block.index("if ready:"):block.index("# Never reveal an unproven native destination")]
    assert "self._show_embedded_host()" in ready
    fallback = block[block.index("# Never reveal an unproven native destination"):]
    assert 'current["software_fallback_reason"] = "visible-surface"' in fallback
    assert "self._show_chromium_software_surface(target_id)" in fallback


def test_deferred_native_retry_reuses_hidden_frame_gate():
    block = inspect.getsource(net.wait_for_embedded_chromium_native_frame)
    assert '_wait_for_attached_first_frame' in block
    assert 'session["dwm_force_full_recrop"] = True' in block
    assert 'session["deferred_native_frame_ready"] = ready' in block
