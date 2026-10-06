"""Crea accesos directos con icono en el Escritorio y en el menú Inicio.

El acceso directo lleva la misma identidad de app (AppUserModelID) que la
ventana, para que en la barra de tareas el icono anclado y la ventana abierta
sean uno solo.

También pone al día los accesos de versiones anteriores (la carpeta se
llamaba capturador_silksong y la app "Capturador Silksong"): borra los viejos
y corrige en su lugar el que esté anclado a la barra de tareas.
"""

import os
import sys
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA))

from capturador import APP_ID, CONGELADO  # noqa: E402

NOMBRE = "Capturador.lnk"
NOMBRE_VIEJO = "Capturador Silksong.lnk"
CARPETA_VIEJA = "capturador_silksong"
ARG_BANDEJA = "--bandeja"


def objetivo(argumentos=""):
    """(programa, argumentos, carpeta de trabajo, icono) para abrir la app."""
    if CONGELADO:  # instalada como .exe
        exe = Path(sys.executable)
        return exe, argumentos, exe.parent, f"{exe},0"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    return pythonw, f'"{CARPETA / "app.pyw"}" {argumentos}'.strip(), CARPETA, f"{CARPETA / 'icono.ico'},0"


def _vincular(link, argumentos):
    programa, args, trabajo, icono = objetivo(argumentos)
    archivo, indice = icono.rsplit(",", 1)
    link.SetPath(str(programa))
    link.SetArguments(args)
    link.SetWorkingDirectory(str(trabajo))
    link.SetIconLocation(archivo, int(indice))


def crear(ruta, argumentos=""):
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell

    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
    _vincular(link, argumentos)
    link.SetDescription("Fotos, animaciones y temporizadores con el mando o el teclado")

    store = link.QueryInterface(propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
    store.Commit()

    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(ruta), 0)


def _argumentos_de(ruta):
    import pythoncom
    from win32com.shell import shell
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
    link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(ruta))
    return link, link.GetArguments()


def carpetas():
    from win32com.shell import shell, shellcon
    ruta = lambda csidl: Path(shell.SHGetFolderPath(0, csidl, None, 0))  # noqa: E731
    return {
        "escritorio": ruta(shellcon.CSIDL_DESKTOPDIRECTORY),
        "inicio_menu": ruta(shellcon.CSIDL_PROGRAMS),
        "inicio_windows": ruta(shellcon.CSIDL_STARTUP),
        "barra": Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Internet Explorer" / "Quick Launch"
                 / "User Pinned" / "TaskBar",
    }


def actualizar_viejos():
    """Borra los accesos de la versión anterior y arregla el anclado a la barra de tareas."""
    import pythoncom
    c = carpetas()
    hechos = []
    for clave in ("escritorio", "inicio_menu"):
        viejo = c[clave] / NOMBRE_VIEJO
        if viejo.exists():
            viejo.unlink()
            hechos.append(f"borrado {viejo}")
    viejo = c["inicio_windows"] / NOMBRE_VIEJO
    if viejo.exists():  # seguía abriéndose con Windows: pasar al acceso nuevo
        viejo.unlink()
        crear(c["inicio_windows"] / NOMBRE, ARG_BANDEJA)
        hechos.append("inicio con Windows actualizado")
    if c["barra"].exists():
        for lnk in c["barra"].glob("*.lnk"):
            try:
                link, args = _argumentos_de(lnk)
            except Exception:
                continue
            if CARPETA_VIEJA in args.lower() and "app.pyw" in args.lower():
                _vincular(link, "")
                link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(lnk), 0)
                hechos.append(f"icono anclado actualizado ({lnk.name})")
    return hechos


def main():
    if os.name != "nt":
        sys.exit("Esto solo funciona en Windows.")
    try:
        import win32com.shell  # noqa: F401
    except ImportError:
        sys.exit("Falta pywin32. Ejecuta instalar.bat (o: py -m pip install pywin32).")

    for hecho in actualizar_viejos():
        print(f"  {hecho}")
    c = carpetas()
    print("Creando accesos directos:")
    for clave in ("escritorio", "inicio_menu"):
        ruta = c[clave] / NOMBRE
        crear(ruta)
        print(f"  {ruta}")

    print()
    print("Listo. Para anclarla a la barra de tareas (si no lo estaba):")
    print("  Busca 'Capturador' en Inicio > clic derecho > Anclar a la barra de tareas.")
    print("  (Ánclala desde Inicio, no desde la ventana abierta.)")


if __name__ == "__main__":
    main()
