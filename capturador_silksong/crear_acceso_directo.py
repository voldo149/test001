"""Crea accesos directos con icono en el Escritorio y en el menú Inicio.

El acceso directo lleva la misma identidad de app (AppUserModelID) que la
ventana, para que en la barra de tareas el icono anclado y la ventana abierta
sean uno solo.
"""

import os
import sys
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA))

from capturador import APP_ID  # noqa: E402

NOMBRE = "Capturador Silksong.lnk"


def crear(ruta, pythonw, argumentos=""):
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell

    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
    link.SetPath(str(pythonw))
    link.SetArguments(f'"{CARPETA / "app.pyw"}" {argumentos}'.strip())
    link.SetWorkingDirectory(str(CARPETA))
    link.SetIconLocation(str(CARPETA / "icono.ico"), 0)
    link.SetDescription("Fotos y temporizadores con el mando")

    store = link.QueryInterface(propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
    store.Commit()

    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(ruta), 0)


def main():
    if os.name != "nt":
        sys.exit("Esto solo funciona en Windows.")
    try:
        from win32com.shell import shell, shellcon
    except ImportError:
        sys.exit("Falta pywin32. Ejecuta instalar.bat (o: py -m pip install pywin32).")

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        sys.exit(f"No se encontró {pythonw}")

    print("Creando accesos directos:")
    for csidl in (shellcon.CSIDL_DESKTOPDIRECTORY, shellcon.CSIDL_PROGRAMS):
        ruta = Path(shell.SHGetFolderPath(0, csidl, None, 0)) / NOMBRE
        crear(ruta, pythonw)
        print(f"  {ruta}")

    print()
    print("Listo. Para anclarla a la barra de tareas:")
    print("  1. Si ya tenías un icono anclado: clic derecho > Desanclar.")
    print("  2. Busca 'Capturador Silksong' en Inicio > clic derecho > Anclar a la barra de tareas.")
    print("  (Ánclala desde Inicio, no desde la ventana abierta.)")


if __name__ == "__main__":
    main()
