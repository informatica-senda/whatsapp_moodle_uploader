@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo No se pudieron instalar las dependencias. Comprueba que Python este instalado.
  pause
  exit /b 1
)
py app.py
