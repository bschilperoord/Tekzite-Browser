"""Verify Tekzite's real spawn method survives parent OneFile cleanup."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def run():
    project = Path(__file__).resolve().parents[1]
    tree = ast.parse((project / 'main.py').read_text(encoding='utf-8'))
    app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'BrowserApp')
    spawn = next(node for node in app.body if isinstance(node, ast.FunctionDef) and node.name == '_spawn_browser_process')
    with tempfile.TemporaryDirectory(prefix='tekzite-onefile-restart-') as directory:
        root = Path(directory)
        entry = root / 'probe.py'
        entry.write_text('''import os, sys, subprocess, json, time
from pathlib import Path
from types import SimpleNamespace
def _profile_slug(value):
    return value
''' + ast.unparse(spawn) + '''
report = Path(os.environ['TEKZITE_PROBE_REPORT'])
release = Path(os.environ['TEKZITE_PROBE_RELEASE'])
if os.environ.get('TEKZITE_PROBE_CHILD') == '1':
    deadline = time.monotonic() + 40
    while not release.exists():
        if time.monotonic() > deadline:
            raise RuntimeError('Parent cleanup was never confirmed')
        time.sleep(.05)
    manifest = Path(sys._MEIPASS) / 'chromium_zoom_extension' / 'manifest.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    report.write_text(json.dumps({'manifest_readable': True, 'name': data['name'],
        'child_extraction': sys._MEIPASS, 'parent_extraction': os.environ['TEKZITE_PROBE_PARENT']}))
else:
    os.environ['TEKZITE_PROBE_PARENT'] = sys._MEIPASS
    os.environ['TEKZITE_PROBE_CHILD'] = '1'
    _spawn_browser_process(SimpleNamespace(_profile_name='Default'))
''', encoding='utf-8')
        command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                   '--console', '--distpath', str(root / 'dist'), '--workpath', str(root / 'work'),
                   '--specpath', str(root), '--add-data',
                   str(project / 'chromium_zoom_extension') + os.pathsep + 'chromium_zoom_extension', str(entry)]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        executable = root / 'dist' / ('probe.exe' if os.name == 'nt' else 'probe')
        report = root / 'result.json'; release = root / 'release'
        environment = {**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1',
                       'TEKZITE_PROBE_REPORT': str(report), 'TEKZITE_PROBE_RELEASE': str(release)}
        environment.pop('TEKZITE_PROBE_CHILD', None)
        with open(root / 'probe.log', 'w') as log:
            parent = subprocess.Popen([str(executable)], env=environment, stdout=log, stderr=log)
            assert parent.wait(timeout=30) == 0, (root / 'probe.log').read_text()
            # Only let the child inspect resources once the parent bootloader exited.
            release.touch()
            deadline = time.monotonic() + 20
            while not report.exists():
                if time.monotonic() > deadline:
                    raise RuntimeError('Restart child lost its manifest: ' + (root / 'probe.log').read_text())
                time.sleep(.05)
            result = json.loads(report.read_text())
            assert result['child_extraction'] != result['parent_extraction'], result
            assert not Path(result['parent_extraction']).exists(), 'Parent extraction was not cleaned up'
            assert result['manifest_readable'] is True
            # Wait for the independent child bootloader to release its resources too.
            deadline = time.monotonic() + 10
            while Path(result['child_extraction']).exists() and time.monotonic() < deadline:
                time.sleep(.05)
            assert not Path(result['child_extraction']).exists(), 'Child extraction was not cleaned up'
            print(json.dumps({'parent_cleanup_confirmed': True, 'independent_child_resources': True,
                              'manifest_readable_after_restart': True, 'child_cleanup_confirmed': True}))


if __name__ == '__main__':
    run()
