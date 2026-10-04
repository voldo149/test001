"""Crea accesos directos con icono en el Escritorio y en el menú Inicio."""

import os
import subprocess
import sys
from pathlib import Path

CARPETA = Path(__file__).resolve().parent

# PowerShell recibe las rutas por variables de entorno para evitar problemas con comillas.
SCRIPT = r"""
$shell = New-Object -ComObject WScript.Shell
foreach ($carpeta in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $shell.CreateShortcut((Join-Path $carpeta 'Capturador Silksong.lnk'))
    $lnk.TargetPath = $env:CS_PYTHONW
    $lnk.Arguments = '"' + $env:CS_APP + '"'
    $lnk.WorkingDirectory = $env:CS_CARPETA
    $lnk.IconLocation = $env:CS_ICONO + ',0'
    $lnk.Description = 'Fotos y temporizadores con el mando'
    $lnk.Save()
    Write-Output ('  ' + $lnk.FullName)
}
"""


def main():
    if os.name != "nt":
        sys.exit("Esto solo funciona en Windows.")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        sys.exit(f"No se encontró {pythonw}")
    env = dict(os.environ,
               CS_PYTHONW=str(pythonw),
               CS_APP=str(CARPETA / "app.pyw"),
               CS_CARPETA=str(CARPETA),
               CS_ICONO=str(CARPETA / "icono.ico"))
    print("Creando accesos directos:")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", SCRIPT],
                   env=env, check=True)
    print("Listo. Para abrirla con UN clic: busca 'Capturador Silksong' en Inicio,")
    print("clic derecho > Anclar a la barra de tareas.")


if __name__ == "__main__":
    main()
