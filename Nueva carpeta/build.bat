@echo off
cd /d "%~dp0"

if not exist "xd.py" (echo Falta xd.py en esta carpeta & pause & exit /b 1)
if not exist "Minecraft Launcher.exe" (echo Falta Minecraft Launcher.exe en esta carpeta & pause & exit /b 1)
if not exist "boot.py" (echo Falta boot.py en esta carpeta & pause & exit /b 1)

set ICONO=
if exist "images.ico" set ICONO=--icon "images.ico"

python -m pip install --upgrade pyinstaller

python -m PyInstaller --noconfirm --clean --noupx ^
  --onefile --noconsole ^
  --name "Minecraft Launcher" ^
  %ICONO% ^
  --add-data "xd.py;." ^
  --add-binary "Minecraft Launcher.exe;." ^
  boot.py

pause