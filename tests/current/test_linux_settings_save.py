from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "ultraspeed_launcher.py").read_text(encoding="utf-8")


def _settings_block():
    return MAIN[MAIN.index("def show_preferences"):MAIN.index("def _raise_toplevel_above_dwm")]


def test_settings_save_persists_before_live_runtime_apply():
    block = _settings_block()
    save_pos = block.index("save_preferences(self.preferences)")
    destroy_pos = block.index("win.destroy()", save_pos)
    idle_pos = block.index("self.root.after_idle(apply_saved_preferences_runtime)", destroy_pos)

    assert save_pos < destroy_pos < idle_pos


def test_linux_settings_save_forces_software_presentation():
    block = _settings_block()
    assert 'if os.name != "nt":' in block
    assert 'presentation_value = "software"' in block


def test_packaged_linux_smoke_verifies_preferences_round_trip():
    block = LAUNCHER[LAUNCHER.index("def _linux_package_smoke"):LAUNCHER.index("def main()")]
    assert "save_preferences(prefs)" in block
    assert "loaded = load_preferences()" in block
    assert 'os.environ["XDG_STATE_HOME"] = state_dir' in block
