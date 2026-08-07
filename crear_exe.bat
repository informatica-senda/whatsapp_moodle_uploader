@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name "Senda_Moodle_WhatsApp" app.py
if exist "dist\Senda_Moodle_WhatsApp.exe" (
  echo.
  echo EXE creado en: %CD%\dist\Senda_Moodle_WhatsApp.exe
) else (
  echo No se pudo crear el EXE.
)
pause
