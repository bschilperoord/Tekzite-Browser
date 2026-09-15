from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
NET = (ROOT / 'engine' / 'net.py').read_text(encoding='utf-8')



def test_tab_activation_is_off_tk_thread():
    block = MAIN[MAIN.index('def _switch_tab'):MAIN.index('def _close_tab')]
    assert '_tab_switch_executor.submit(activate_embedded_chromium_target' in block
    assert 'self.root.after(8, finish_switch)' in block


def test_tab_switches_are_serialized():
    assert 'ThreadPoolExecutor(max_workers=1, thread_name_prefix="tekzite-tab-switch")' in MAIN
    assert '_tab_switch_serial' in MAIN
    assert '_tab_switch_pending_id' in MAIN


def test_ui_commit_happens_after_activation_result():
    switch = MAIN[MAIN.index('def _switch_tab'):MAIN.index('def _close_tab')]
    assert 'activated = bool(future.result())' in switch
    assert 'self._commit_tab_switch(current_target)' in switch
    assert switch.index('activated = bool(future.result())') < switch.index('self._commit_tab_switch(current_target)')


def test_native_activation_pulses_dwm_without_resize():
    fn = NET[NET.index('def activate_embedded_chromium_target'):NET.index('def close_embedded_chromium_target')]
    assert 'RedrawWindow' in fn
    assert 'DwmFlush()' in fn
    assert 'resize_embedded_chromium' not in fn
