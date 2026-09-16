# Release checklist

1. Update `BROWSER_VERSION` in `main.py`.
2. Add release notes to `CHANGELOG.md`.
3. Run:

   ```powershell
   python -m py_compile main.py engine\net.py tekzite_network.py tekzite_network_fast.py ultraspeed_runtime.py ultraspeed_launcher.py
   python -m pytest -q
   python tools\doctor.py
   powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
   ```

4. Manually smoke-test on Windows:
   - Startpage input and search;
   - YouTube load/profile popup;
   - native zoom at 100% and 150%;
   - text selection;
   - tab switching and restore-closed-tab;
   - maximized/restored DWM geometry;
   - Preferences dialog;
   - Microsoft account/page access;
   - ad blocker toggle after restart;
   - New Private Window opens a distinct temporary profile and leaves no saved private session/history;
   - Site Info reports the current origin and Clear site data affects only that origin;
   - Extension Manager can load a small unpacked test extension after restart.
   - `dist\TekziteBrowser.exe` starts and closes normally;
   - closing the OneFile build leaves no `tekzite-network.exe` child running and shows no `_MEI...` cleanup warning.
5. Tag the release as `vX.Y.Z` and attach the Windows OneFile executable and any source artifacts as appropriate.
