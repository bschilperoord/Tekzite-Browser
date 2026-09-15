from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
NET = (ROOT / 'engine' / 'net.py').read_text(encoding='utf-8')


def test_version_80():
    assert 'BROWSER_VERSION = "8.0"' in MAIN


def test_live_page_state_and_favicon_channel():
    assert 'def get_embedded_chromium_page_state' in NET
    assert 'favicon_b64' in NET
    assert 'document.title' in NET
    assert 'document.readyState' in NET
    assert 'def _schedule_page_state_poll' in MAIN
    assert 'favicon_photo' in MAIN


def test_find_in_page():
    assert 'def find_embedded_chromium_text' in NET
    assert 'window.find(' in NET
    assert 'def _show_find_bar' in MAIN
    assert 'def _find_in_page' in MAIN
    assert '<Control-f>' in MAIN


def test_restore_and_tab_keyboard_ux():
    assert 'def _restore_closed_tab' in MAIN
    assert '<Control-Shift-T>' in MAIN
    assert '<Control-Tab>' in MAIN
    assert '<Control-Shift-Tab>' in MAIN
    assert 'def _cycle_tab' in MAIN
    assert 'def _switch_tab_by_index' in MAIN


def test_middle_click_and_paste_go():
    assert '<Button-2>' in MAIN
    assert 'def _paste_and_go' in MAIN
    assert 'Paste and Go' in MAIN
    assert '<Control-Shift-v>' in MAIN


def test_fast_switch_contract_preserved():
    assert 'fast_native_switch = bool(' in MAIN
    block = MAIN[MAIN.index('fast_native_switch = bool('):MAIN.index('# Blank/unloaded tab:', MAIN.index('fast_native_switch = bool('))]
    assert '_show_embedded_host()' in block  # fallback only remains
    assert 'self._chromium_frame_target_id = target["chromium_target_id"]' in block
