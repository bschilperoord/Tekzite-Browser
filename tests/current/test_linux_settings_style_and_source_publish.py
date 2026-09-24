from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "linux-preview.yml").read_text(encoding="utf-8")


def _settings_block():
    return MAIN[MAIN.index("def show_preferences"):MAIN.index("def _raise_toplevel_above_dwm")]


def test_linux_settings_controls_do_not_use_tk_focus_boxes():
    block = _settings_block()
    assert block.count('tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat",') == 16
    assert 'text="Cancel"' in block and 'highlightthickness=0' in block
    assert 'text="Save"' in block and 'highlightthickness=0' in block


def test_linux_preview_publishes_exact_source_archive():
    assert 'git archive --format=tar --prefix="${source_name}/" "$GITHUB_SHA"' in WORKFLOW
    assert '${{ steps.package.outputs.source_name }}.tar.gz' in WORKFLOW
    assert 'git tag -f "$tag" "$GITHUB_SHA"' in WORKFLOW
    assert 'git push origin "refs/tags/$tag" --force' in WORKFLOW
