"""
Icono en la bandeja del sistema (junto al reloj) e "Iniciar con Windows".

pystray es opcional: si no está instalado o falla, la app sigue igual, solo
que sin icono en la bandeja.
"""

import os
import sys
import threading
from pathlib import Path

from PIL import Image

CARPETA = Path(__file__).resolve().parent
NOMBRE_INICIO = "Capturador Silksong.lnk"
ARG_BANDEJA = "--bandeja"


class Bandeja:
    """Icono con menú Abrir / Salir. Las acciones llegan a la ventana por su cola de eventos."""

    def __init__(self, eventos, titulo):
        self.eventos = eventos
        self.icono = None
        self.error = None
        try:
            import pystray
            imagen = Image.open(CARPETA / "icono.ico")
            imagen.size  # el tamaño más grande del .ico
            menu = pystray.Menu(
                pystray.MenuItem("Abrir", lambda: self.eventos.put(("bandeja", "abrir")), default=True),
                pystray.MenuItem("Salir", lambda: self.eventos.put(("bandeja", "salir"))),
            )
            self.icono = pystray.Icon("CapturadorSilksong", imagen.convert("RGBA"), titulo, menu)
            threading.Thread(target=self.icono.run, daemon=True).start()
        except Exception as e:
            self.error = str(e)
            self.icono = None

    @property
    def disponible(self):
        return self.icono is not None

    def titulo(self, texto):
        if self.icono is not None and self.icono.title != texto:
            try:
                self.icono.title = texto[:120]  # Windows corta el texto del icono
            except Exception:
                pass

    def cerrar(self):
        if self.icono is not None:
            try:
                self.icono.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------- inicio con Windows

def _ruta_inicio():
    from win32com.shell import shell, shellcon
    return Path(shell.SHGetFolderPath(0, shellcon.CSIDL_STARTUP, None, 0)) / NOMBRE_INICIO


def inicio_con_windows():
    """True si existe el acceso directo en la carpeta Inicio de Windows."""
    if os.name != "nt":
        return False
    try:
        return _ruta_inicio().exists()
    except Exception:
        return False


def activar_inicio_con_windows(activar):
    """Crea o borra el acceso directo que abre la app minimizada en la bandeja al iniciar Windows."""
    if os.name != "nt":
        raise RuntimeError("solo funciona en Windows")
    ruta = _ruta_inicio()
    if activar:
        import crear_acceso_directo
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        crear_acceso_directo.crear(ruta, pythonw if pythonw.exists() else Path(sys.executable), ARG_BANDEJA)
    elif ruta.exists():
        ruta.unlink()
