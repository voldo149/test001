@echo off
chcp 65001 >nul
rem Actualiza el Capturador desde GitHub (aunque git diga "up to date") y lo abre.
rem Tu configuracion, tus tiempos y tus fotos no se tocan.

rem Se ejecuta desde una copia en TEMP: git va a reemplazar este mismo archivo.
if not "%~1"=="--copia" (
    copy /y "%~f0" "%TEMP%\actualizar_capturador.bat" >nul
    "%TEMP%\actualizar_capturador.bat" --copia "%~dp0"
    exit /b
)
set "CARPETA=%~2"

echo Cerrando el Capturador...
powershell -NoProfile -Command "Get-Process Capturador -ErrorAction SilentlyContinue | Stop-Process -Force; Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*app.pyw*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 /nobreak >nul

echo.
echo Bajando la ultima version...
cd /d "%CARPETA%.."
git fetch origin
if errorlevel 1 goto error
git checkout claude/adoring-darwin-pktdfp
git reset --hard origin/claude/adoring-darwin-pktdfp
if errorlevel 1 goto error

echo.
git log -1 --format="Version actual: %%s"
echo.
echo Abriendo el Capturador...
where pyw >nul 2>&1
if errorlevel 1 (
    start "" pythonw "%CARPETA%app.pyw"
) else (
    start "" pyw "%CARPETA%app.pyw"
)
timeout /t 3 >nul
exit /b

:error
echo.
echo [!] No se pudo actualizar. Revisa tu conexion a internet e intenta otra vez.
pause
