from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT/'main.py').read_text(encoding='utf-8')
NET = (ROOT/'engine'/'net.py').read_text(encoding='utf-8')

def test_version_75():
    assert 'BROWSER_VERSION = "7.5"' in MAIN

def test_native_switch_has_hot_path():
    assert 'fast_native_switch = bool(' in MAIN
    assert 'self._dwm_surface_ready' in MAIN
    assert 'self.edge_host.winfo_ismapped()' in MAIN

def test_hot_path_does_not_rebuild_dwm_host():
    block = MAIN[MAIN.index('elif fast_native_switch:'):MAIN.index('else:', MAIN.index('elif fast_native_switch:'))]
    assert '_show_embedded_host' not in block
    assert 'resize_embedded_chromium' not in block
    assert '_sync_dwm_host_geometry' not in block
    assert '_chromium_frame_target_id = target["chromium_target_id"]' in block

def test_zoom_deferred_not_all_tabs_on_switch():
    sw = MAIN[MAIN.index('def _switch_tab'):MAIN.index('def _close_tab')]
    assert '_schedule_chromium_zoom_apply(all_tabs=True)' not in sw
    assert 'self.root.after(90' in sw

def test_target_activation_skips_json_list_fast_path():
    fn = NET[NET.index('def activate_embedded_chromium_target'):NET.index('def close_embedded_chromium_target')]
    body = fn[fn.index('session = _start_persistent_chromium_session'): ]
    first_call = body.index('_browser_cdp_call(')
    list_call = body.index('_devtools_json(')
    assert first_call < list_call
    assert 'tab_switch_fast_path_count' in fn

def test_compile_shape_keeps_fallback():
    fn = NET[NET.index('def activate_embedded_chromium_target'):NET.index('def close_embedded_chromium_target')]
    assert 'except Exception:' in fn
    assert '/json/list' in fn
