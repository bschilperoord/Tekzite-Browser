Tekzite Browser installer
=========================

1. Build the browser first from the project root:
   powershell -ExecutionPolicy Bypass -File .\build_windows.ps1

2. Put a real Windows icon at:
   assets\tekzite.ico

3. Install Inno Setup 6.

4. Compile:
   & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" ".\installer\TekziteBrowser.iss"

Installer output:
   installer-dist\Tekzite-Browser-Setup-10.5.47.exe

