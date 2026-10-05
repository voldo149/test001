"""
Aviso pequeño en pantalla (abajo a la izquierda): FOTO, REC, PAUSA…

- Siempre encima, incluso sobre el juego en pantalla completa sin bordes
  (en pantalla completa exclusiva Windows no deja dibujar encima).
- No toma el foco ni recibe clics (el juego no se pausa).
- Excluido de las capturas (WDA_EXCLUDEFROMCAPTURE, Windows 10 2004 o más
  nuevo): se ve en el monitor pero no sale en ninguna foto ni animación.
  Si Windows no lo permite, el aviso se desactiva para no arruinar capturas.
"""

import ctypes
import os
import tkinter as tk
from ctypes import wintypes

FONDO = "#0d1524"
BORDE = "#1e2a3e"
TEXTO = "#e8eef7"
TENUE = "#8391a7"
FAMILIA = "Segoe UI" if os.name == "nt" else "DejaVu Sans"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020   # los clics lo atraviesan
WS_EX_TOOLWINDOW = 0x00000080    # sin botón en la barra de tareas
WS_EX_NOACTIVATE = 0x08000000    # nunca toma el foco
WDA_EXCLUDEFROMCAPTURE = 0x00000011
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40


class AvisoPantalla:
    MARGEN = 28

    def __init__(self, root):
        self.root = root
        self.disponible = False
        self.motivo = ""
        self._ocultar_id = None
        self._persistente = False
        self.hwnd = None

        self.ventana = tk.Toplevel(root, bg=BORDE)
        self.ventana.overrideredirect(True)
        self.ventana.attributes("-topmost", True)
        try:
            self.ventana.attributes("-alpha", 0.92)
        except tk.TclError:
            pass
        marco = tk.Frame(self.ventana, bg=FONDO, padx=14, pady=8)
        marco.pack(padx=1, pady=1)
        self.punto = tk.Label(marco, text="●", bg=FONDO, fg=TEXTO, font=(FAMILIA, 12))
        self.punto.pack(side="left")
        self.titulo = tk.Label(marco, text="", bg=FONDO, fg=TEXTO, font=(FAMILIA, 11, "bold"))
        self.titulo.pack(side="left", padx=(6, 8))
        self.texto = tk.Label(marco, text="", bg=FONDO, fg=TENUE, font=(FAMILIA, 11))
        self.texto.pack(side="left")
        self.ventana.update_idletasks()
        self._preparar()

    def _preparar(self):
        if os.name != "nt":
            # Fuera de Windows no se puede excluir de capturas: solo para pruebas.
            self.disponible = True
            self.ventana.withdraw()
            return
        try:
            u32 = ctypes.windll.user32
            u32.GetParent.argtypes = [wintypes.HWND]
            u32.GetParent.restype = wintypes.HWND
            u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            u32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, wintypes.UINT]
            self.hwnd = u32.GetParent(self.ventana.winfo_id()) or self.ventana.winfo_id()
            estilo = u32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            u32.SetWindowLongW(self.hwnd, GWL_EXSTYLE,
                               estilo | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            if not u32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE):
                self.motivo = "tu versión de Windows no permite ocultar el aviso de las capturas"
                u32.ShowWindow(self.hwnd, SW_HIDE)
                return
            u32.ShowWindow(self.hwnd, SW_HIDE)
            self.disponible = True
        except Exception as e:
            self.motivo = f"no se pudo preparar ({e})"
            try:
                self.ventana.withdraw()
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ mostrar

    def mostrar(self, titulo, texto="", color=TEXTO, segundos=1.8):
        """Muestra el aviso. segundos=None: queda hasta que se muestre otro u ocultar()."""
        if not self.disponible:
            return
        self.punto.configure(fg=color)
        self.titulo.configure(text=titulo, fg=color)
        self.texto.configure(text=texto)
        self.ventana.update_idletasks()
        alto = self.ventana.winfo_reqheight()
        x = self.MARGEN
        y = self.root.winfo_screenheight() - alto - self.MARGEN
        self.ventana.geometry(f"+{x}+{y}")
        self._ver()
        if self._ocultar_id:
            self.root.after_cancel(self._ocultar_id)
            self._ocultar_id = None
        self._persistente = segundos is None
        if segundos is not None:
            self._ocultar_id = self.root.after(int(segundos * 1000), self.ocultar)

    def actualizar_texto(self, texto):
        """Cambia solo el texto (para el contador de REC) sin reiniciar nada."""
        if self.disponible and self.texto.cget("text") != texto:
            self.texto.configure(text=texto)

    def ocultar(self):
        self._ocultar_id = None
        self._persistente = False
        if not self.disponible:
            return
        if self.hwnd:
            ctypes.windll.user32.ShowWindow(self.hwnd, SW_HIDE)
        else:
            self.ventana.withdraw()

    def _ver(self):
        if self.hwnd:
            u32 = ctypes.windll.user32
            # Mostrar sin activar y asegurar que quede encima del juego.
            u32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            u32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        else:
            self.ventana.deiconify()
            self.ventana.lift()
