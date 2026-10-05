"""
Indicador mínimo en pantalla: un circulito abajo a la izquierda.

- Gris: hay un temporizador corriendo.
- Rojo: grabando una animación.
- Destello verde (~0.3 s): se tomó una foto.
- No aparece si no hay temporizador corriendo.

- Siempre encima, incluso sobre el juego en pantalla completa sin bordes
  (en pantalla completa exclusiva Windows no deja dibujar encima).
- No toma el foco ni recibe clics (el juego no se pausa).
- Excluido de las capturas (WDA_EXCLUDEFROMCAPTURE, Windows 10 2004 o más
  nuevo): se ve en el monitor pero no sale en ninguna foto ni animación.
  Si Windows no lo permite, el indicador se desactiva para no arruinar capturas.
"""

import ctypes
import os
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

GRIS = "#8a94a6"
ROJO = "#ff4d63"
VERDE = "#2ee59d"      # verde esmeralda
CONTORNO = "#0a101d"   # anillo oscuro para que se vea sobre fondos claros
CLAVE = "#ff00fe"      # color que Windows vuelve transparente (el fondo de la ventana)
DIAMETRO = 16
MARGEN = 22
DESTELLO_MS = 300

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020   # los clics lo atraviesan
WS_EX_TOOLWINDOW = 0x00000080    # sin botón en la barra de tareas
WS_EX_NOACTIVATE = 0x08000000    # nunca toma el foco
WDA_EXCLUDEFROMCAPTURE = 0x00000011
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40


def _hex(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def dibujar_circulo(color, tam):
    """Círculo con borde suave.

    El suavizado se hace contra el anillo oscuro (no contra el fondo
    transparente): si se mezclara con el color clave, en Windows quedaría un
    halo rosa alrededor.
    """
    base = Image.new("RGB", (tam, tam), _hex(CLAVE))
    mascara = Image.new("L", (tam, tam), 0)
    ImageDraw.Draw(mascara).ellipse((0, 0, tam - 1, tam - 1), fill=255)
    escala = 4
    grande = Image.new("RGB", (tam * escala, tam * escala), _hex(CONTORNO))
    borde = 2 * escala
    ImageDraw.Draw(grande).ellipse((borde, borde, tam * escala - 1 - borde, tam * escala - 1 - borde),
                                   fill=_hex(color))
    base.paste(grande.resize((tam, tam), Image.LANCZOS), (0, 0), mascara)
    return base


class AvisoPantalla:
    def __init__(self, root):
        self.root = root
        self.disponible = False
        self.motivo = ""
        self.hwnd = None
        self._base = "oculto"     # "oculto", "listo" (gris) o "rec" (rojo)
        self._destello_id = None
        self._visible = False

        tam = DIAMETRO + 4
        self.ventana = tk.Toplevel(root, bg=CLAVE)
        self.ventana.overrideredirect(True)
        self.ventana.attributes("-topmost", True)
        try:
            self.ventana.attributes("-transparentcolor", CLAVE)  # solo Windows
        except tk.TclError:
            pass
        self.lienzo = tk.Canvas(self.ventana, width=tam, height=tam, bg=CLAVE, highlightthickness=0, bd=0)
        self.lienzo.pack()
        self._imagenes = {c: ImageTk.PhotoImage(dibujar_circulo(c, tam), master=self.ventana)
                          for c in (GRIS, ROJO, VERDE)}
        self.color = GRIS
        self.circulo = self.lienzo.create_image(0, 0, anchor="nw", image=self._imagenes[GRIS])
        alto = root.winfo_screenheight()
        self.ventana.geometry(f"{tam}x{tam}+{MARGEN}+{alto - tam - MARGEN}")
        self.ventana.update_idletasks()
        self._preparar()

    def _preparar(self):
        if os.name != "nt":
            # Fuera de Windows no se puede excluir de capturas: solo para pruebas.
            self.disponible = True
            self.ventana.withdraw()
            return
        try:
            from ctypes import wintypes
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
                self.motivo = "tu versión de Windows no permite ocultarlo de las capturas"
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

    # ------------------------------------------------------------------ estado

    def estado(self, base):
        """'oculto' (sin temporizador), 'listo' (gris) o 'rec' (rojo)."""
        if base == self._base:
            return
        self._base = base
        if self._destello_id is None:  # durante un destello se aplica al terminar
            self._aplicar()

    def destello(self):
        """Flash verde de unos cuadros al tomar una foto."""
        if not self.disponible:
            return
        if self._destello_id:
            self.root.after_cancel(self._destello_id)
        self._pintar(VERDE)
        self._ver(True)
        self._destello_id = self.root.after(DESTELLO_MS, self._fin_destello)

    def _fin_destello(self):
        self._destello_id = None
        self._aplicar()

    def ocultar(self):
        self._base = "oculto"
        self._aplicar()

    def _aplicar(self):
        if not self.disponible:
            return
        if self._base == "oculto":
            self._ver(False)
        else:
            self._pintar(ROJO if self._base == "rec" else GRIS)
            self._ver(True)

    def _pintar(self, color):
        if color != self.color:
            self.color = color
            self.lienzo.itemconfigure(self.circulo, image=self._imagenes[color])

    def _ver(self, visible):
        if visible == self._visible and not visible:
            return
        self._visible = visible
        if self.hwnd:
            u32 = ctypes.windll.user32
            if visible:
                # Mostrar sin activar y asegurar que quede encima del juego.
                u32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
                u32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
            else:
                u32.ShowWindow(self.hwnd, SW_HIDE)
        elif visible:
            self.ventana.deiconify()
            self.ventana.lift()
        else:
            self.ventana.withdraw()
