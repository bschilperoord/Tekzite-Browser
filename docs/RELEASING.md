# Release checklist

1. Choose the next version and synchronize active metadata:

   ```powershell
   python tools\sync_version.py 10.5.63
   python tools\sync_version.py 10.5.63 --check
   ```

2. Add release notes to `CHANGELOG.md`.
3. Run the local verification set:

   ```powershell
   python -m py_compile main.py browser_state.py browser_features.py engine\net.py engine\features.py tekzite_network.py tools\doctor.py tools\sync_version.py
   python -m pytest -q
   node tests\current\test_extension_features.cjs
   python tools\doctor.py
   powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
   ```

4. Manually smoke-test on Windows:
   - Startpage input and search;
   - YouTube load/profile popup and Google sign-in handoff;
   - native zoom at 100% and 150%;
   - text selection;
   - tab switching and restore-closed-tab;
   - maximize, restore, minimize/taskbar restore, and window dragging;
   - Preferences dialog;
   - Microsoft account/page access;
   - ad blocker toggle after restart;
   - New Private Window opens a distinct temporary profile and leaves no saved private session/history;
   - Site Info reports the current origin and Clear site data affects only that origin;
   - Extension Manager can load a small unpacked test extension after restart;
   - `dist\TekziteBrowser.exe` starts and closes normally;
   - closing the OneFile build leaves no `tekzite-network.exe` child running and shows no `_MEI...` cleanup warning.

5. Commit and push the release source to `main`. Create and push an annotated tag that exactly matches `BROWSER_VERSION`, for example:

   ```powershell
   git tag -a v10.5.63 -m "Tekzite Browser v10.5.63"
   git push origin main
   git push origin v10.5.63
   ```

6. Pushing the `vX.Y.Z` tag triggers `.github/workflows/publish-windows-release.yml`. The workflow validates the version, runs the regression suite and extension tests, builds the Windows executable, verifies its version resource, creates binary/source ZIPs and SHA-256 checksums, and publishes the GitHub release.
