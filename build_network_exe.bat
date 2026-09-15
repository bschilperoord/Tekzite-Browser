@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --name tekzite-network tekzite_network.py
if errorlevel 1 exit /b 1
copy /Y "dist\tekzite-network.exe" ".\tekzite-network.exe"
echo.
echo Built: %CD%\tekzite-network.exe
