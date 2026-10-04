@echo off
cd /d "%~dp0"
echo Instalando dependencias...
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo [!] Fallo la instalacion de dependencias.
  pause
  exit /b 1
)
py crear_acceso_directo.py
pause
