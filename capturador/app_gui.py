"""
Ventana de Capturador: fotos, animaciones y temporizadores con el mando.

Estilo oscuro inspirado en el editor de guías de Speedrunz. La ventana nunca
se pone al frente sola ni toma el foco, así que se puede dejar abierta
(o minimizada) mientras juegas o escribes.
"""

import ctypes
import multiprocessing
import os
import queue
import shutil
import sys
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

import animacion
import bandeja
import capturador as cap
import sonidos
import trabajador
from aviso_pantalla import AvisoPantalla
from tiempos import RegistroTiempos, formato_duracion

CARPETA = cap.CARPETA_DATOS          # config, tiempos, errores
ICONO = cap.CARPETA_SCRIPT / "icono.ico"
LOG_ERRORES = CARPETA / "errores.log"
TITULO = "Capturador"
LATIDO_CADA_MS = 30_000
# Si el reloj salta más que esto entre dos refrescos, la PC estuvo suspendida:
# los temporizadores se detienen en el último momento en que la app estaba viva.
SALTO_SUSPENSION_SEG = 600
MAX_MINIATURAS = 24
TAM_MINIATURA = (132, 74)
EXTENSIONES_FOTO = {".png", ".jpg", ".jpeg", ".webp"}

# --------------------------------------------------------------------------
# Paleta (tomada del editor de guías)
# --------------------------------------------------------------------------

FONDO = "#0a101d"
PANEL = "#0d1524"
TARJETA = "#111a2b"
TARJETA_HOVER = "#16223a"
BORDE = "#1e2a3e"
TEXTO = "#e8eef7"
TENUE = "#8391a7"
VERDE = "#29ce8e"  # verde oficial de la página
VERDE_FONDO = "#113a36"
VERDE_HOVER = "#13493f"
VERDE_BORDE = "#196b53"
VERDE_CLARO = "#caf3e3"
AZUL_FONDO = "#172a4d"
AZUL_HOVER = "#1f3763"
SELECCION = "#13223d"
ROJO = "#ff8a9e"
ROJO_FONDO = "#3a1622"
ROJO_HOVER = "#4a1c2b"

FAMILIA = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
MONO = "Cascadia Mono" if os.name == "nt" else "DejaVu Sans Mono"


def fuente(tam=13, peso="normal", familia=None):
    return ctk.CTkFont(family=familia or FAMILIA, size=tam, weight=peso)


def registrar_error(texto):
    with open(LOG_ERRORES, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{texto}\n")


def texto_espera(segundos):
    return f"{segundos} s" if segundos < 60 else f"{segundos // 60} min"


def ruta_corta(ruta, maximo=40):
    return ruta if len(ruta) <= maximo else "…" + ruta[-(maximo - 1):]


def abrir(ruta):
    if hasattr(os, "startfile"):
        os.startfile(ruta)


def pitido(inicio):
    """Pitido corto (no es un sonido de error de Windows): agudo = inicia, grave = para."""
    sonidos.reproducir("timer_inicio" if inicio else "timer_fin")


def etiqueta_foto(ruta):
    """silksong_2026-10-04_21-10-05_123_foto1 -> '04/10 21:10 · foto1'."""
    partes = ruta.stem.split("_")
    try:
        fecha = datetime.strptime(f"{partes[1]}_{partes[2]}", "%Y-%m-%d_%H-%M-%S")
        resto = "_".join(partes[4:])
        return f"{fecha:%d/%m %H:%M}" + (f" · {resto}" if resto else "")
    except (IndexError, ValueError):
        return ruta.stem


def sonido_anim(inicio):
    """Dos tonos: subiendo = empieza a grabar, bajando = terminó."""
    sonidos.reproducir("anim_inicio" if inicio else "anim_fin")


def marcar_animacion(img, n):
    """Dibuja sobre la miniatura una etiqueta '▶ 120' para distinguir animaciones."""
    img = img.copy()
    d = ImageDraw.Draw(img, "RGBA")
    try:
        letra = ImageFont.load_default(size=max(14, img.height // 6))
    except TypeError:
        letra = ImageFont.load_default()
    texto = f"{n}" if n else "ANIM"
    x0, y0, alto = 8, 8, max(22, int(img.height / 4.2))
    ancho_txt = d.textlength(texto, font=letra)
    ancho = int(alto * 0.9 + ancho_txt + 10)
    d.rounded_rectangle((x0, y0, x0 + ancho, y0 + alto), radius=alto // 3, fill=(7, 16, 29, 215),
                        outline=(41, 206, 142, 255), width=1)
    t = alto * 0.28
    cx, cy = x0 + alto * 0.45, y0 + alto / 2
    d.polygon([(cx - t * 0.6, cy - t), (cx - t * 0.6, cy + t), (cx + t, cy)], fill=(41, 206, 142, 255))
    d.text((x0 + alto * 0.9, cy), texto, font=letra, fill=(232, 238, 247, 255), anchor="lm")
    return img


def hacer_miniatura(img):
    """Reduce rápido (reduce() es mucho más barato que redimensionar directo)."""
    factor = max(1, min(img.width // (TAM_MINIATURA[0] * 2), img.height // (TAM_MINIATURA[1] * 2)))
    peque = img.reduce(factor) if factor > 1 else img.copy()
    peque.thumbnail((TAM_MINIATURA[0] * 2, TAM_MINIATURA[1] * 2))
    return peque.convert("RGB")


def poner_icono(ventana):
    # Ponerlo de inmediato: así CustomTkinter ya no lo cambia por el suyo a los 200 ms.
    if ICONO.exists() and os.name == "nt":
        try:
            ventana.iconbitmap(str(ICONO))
        except tk.TclError:
            pass


# --------------------------------------------------------------------------
# Piezas visuales reutilizables
# --------------------------------------------------------------------------

def boton(padre, texto, comando, estilo="normal", **kw):
    estilos = {
        "verde": dict(fg_color=VERDE_FONDO, hover_color=VERDE_HOVER, text_color=VERDE_CLARO,
                      border_color=VERDE_BORDE, border_width=1),
        "azul": dict(fg_color=AZUL_FONDO, hover_color=AZUL_HOVER, text_color=TEXTO,
                     border_color="#29406b", border_width=1),
        "rojo": dict(fg_color=ROJO_FONDO, hover_color=ROJO_HOVER, text_color=ROJO,
                     border_color="#5c2433", border_width=1),
        "normal": dict(fg_color=TARJETA, hover_color=TARJETA_HOVER, text_color=TEXTO,
                       border_color=BORDE, border_width=1),
        "fantasma": dict(fg_color="transparent", hover_color=TARJETA_HOVER, text_color=TENUE,
                         border_width=0),
    }
    opciones = dict(corner_radius=8, height=34, font=fuente(13, "bold"))
    opciones.update(estilos[estilo])
    opciones.update(kw)
    return ctk.CTkButton(padre, text=texto, command=comando, **opciones)


def insignia(padre, texto, color=TENUE, borde=BORDE):
    """Etiqueta chica en mayúsculas con borde, como 'VISOR' o '2 VISTAS'."""
    return ctk.CTkLabel(padre, text=texto.upper(), font=fuente(10, "bold"), text_color=color,
                        fg_color="transparent", corner_radius=6, height=22, padx=8,
                        border_width=1, border_color=borde)


def titulo_seccion(padre, texto, texto_insignia=None):
    fila = ctk.CTkFrame(padre, fg_color="transparent")
    ctk.CTkLabel(fila, text=texto, font=fuente(14, "bold"), text_color=TEXTO).pack(side="left")
    etiqueta = None
    if texto_insignia is not None:
        etiqueta = insignia(fila, texto_insignia)
        etiqueta.pack(side="right")
    return fila, etiqueta


def separador(padre):
    return ctk.CTkFrame(padre, height=1, fg_color=BORDE, corner_radius=0)


class BarraVolumen(tk.Canvas):
    """5 barras de alturas crecientes; tocar una elige ese nivel."""

    NIVELES = 5
    ANCHO, SEPARACION, ALTO = 16, 6, 26

    def __init__(self, padre, nivel, al_cambiar):
        ancho = self.NIVELES * self.ANCHO + (self.NIVELES - 1) * self.SEPARACION
        super().__init__(padre, width=ancho, height=self.ALTO, bg=PANEL, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.nivel = nivel
        self.al_cambiar = al_cambiar
        self.barras = []
        for i in range(self.NIVELES):
            x = i * (self.ANCHO + self.SEPARACION)
            alto = 8 + (self.ALTO - 8) * i / (self.NIVELES - 1)
            self.barras.append(self.create_rectangle(x, self.ALTO - alto, x + self.ANCHO, self.ALTO, width=0))
        self.bind("<Button-1>", self._clic)
        self._pintar()

    def _clic(self, evento):
        nivel = min(self.NIVELES, max(1, int(evento.x // (self.ANCHO + self.SEPARACION)) + 1))
        if nivel != self.nivel:
            self.nivel = nivel
            self._pintar()
        self.al_cambiar(nivel)

    def _pintar(self):
        for i, barra in enumerate(self.barras):
            self.itemconfigure(barra, fill=VERDE if i < self.nivel else BORDE)


class Dialogo(ctk.CTkToplevel):
    """Diálogo oscuro con mensaje, entrada opcional y botones."""

    def __init__(self, padre, titulo, mensaje, botones, entrada=None):
        super().__init__(padre, fg_color=PANEL)
        self.title(titulo)
        self.resizable(False, False)
        self.transient(padre)
        self.resultado = None
        poner_icono(self)

        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True, padx=24, pady=(22, 18))
        ctk.CTkLabel(cuerpo, text=titulo, font=fuente(16, "bold"), text_color=TEXTO).pack(anchor="w")
        ctk.CTkLabel(cuerpo, text=mensaje, font=fuente(13), text_color=TENUE, justify="left",
                     wraplength=380).pack(anchor="w", pady=(6, 0))

        self.entrada = None
        if entrada is not None:
            self.entrada = ctk.CTkEntry(cuerpo, width=380, height=36, fg_color=TARJETA,
                                        border_color=BORDE, text_color=TEXTO, font=fuente(13))
            self.entrada.insert(0, entrada)
            self.entrada.pack(pady=(14, 0))
            self.entrada.bind("<Return>", lambda e: self._elegir(True))

        fila = ctk.CTkFrame(cuerpo, fg_color="transparent")
        fila.pack(fill="x", pady=(18, 0))
        for texto, valor, estilo in reversed(botones):
            boton(fila, texto, lambda v=valor: self._elegir(v), estilo, width=110).pack(side="right", padx=(8, 0))

        self.bind("<Escape>", lambda e: self._elegir(None))
        self.protocol("WM_DELETE_WINDOW", lambda: self._elegir(None))
        self.after(30, self._mostrar, padre)

    def _mostrar(self, padre):
        self.update_idletasks()
        x = padre.winfo_rootx() + (padre.winfo_width() - self.winfo_width()) // 2
        y = padre.winfo_rooty() + (padre.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass
        (self.entrada or self).focus_set()

    def _elegir(self, valor):
        if valor is True and self.entrada is not None:
            valor = self.entrada.get().strip() or None
        self.resultado = valor
        self.destroy()

    @classmethod
    def mostrar(cls, padre, titulo, mensaje, botones=(("Aceptar", True, "verde"),), entrada=None):
        d = cls(padre, titulo, mensaje, botones, entrada)
        padre.wait_window(d)
        return d.resultado

    @classmethod
    def confirmar(cls, padre, titulo, mensaje, si="Sí", estilo="verde"):
        return cls.mostrar(padre, titulo, mensaje, (("Cancelar", False, "normal"), (si, True, estilo))) is True


class TarjetaTimer(ctk.CTkFrame):
    """Tarjeta de un temporizador con tiempo grande y totales."""

    def __init__(self, padre, app, timer):
        super().__init__(padre, fg_color=TARJETA, corner_radius=12, border_width=1, border_color=BORDE)
        self.app = app
        self.nombre = timer["nombre"]
        self._cache = {}

        arriba = ctk.CTkFrame(self, fg_color="transparent")
        arriba.pack(fill="x", padx=16, pady=(14, 0))
        ctk.CTkLabel(arriba, text=self.nombre, font=fuente(15, "bold"), text_color=TEXTO).pack(side="left")
        self.estado = insignia(arriba, "Detenido")
        self.estado.pack(side="right")

        linea = ctk.CTkFrame(self, fg_color="transparent")
        linea.pack(fill="x", padx=16, pady=(4, 0))
        self.lbl_mando = ctk.CTkLabel(linea, text="Clic para seleccionar", font=fuente(12), text_color=TENUE,
                                      anchor="w")
        self.lbl_mando.pack(side="left")
        self.marca = insignia(linea, "Seleccionado", color=VERDE, borde=VERDE_BORDE)

        self.reloj = ctk.CTkLabel(self, text="0:00:00", font=fuente(34, "bold"), text_color=TENUE, anchor="w")
        self.reloj.pack(fill="x", padx=16, pady=(4, 0))

        totales = ctk.CTkFrame(self, fg_color="transparent")
        totales.pack(fill="x", padx=16, pady=(2, 0))
        self.totales = {}
        for clave, texto in (("hoy", "Hoy"), ("semana", "Semana"), ("total", "Total")):
            col = ctk.CTkFrame(totales, fg_color="transparent")
            col.pack(side="left", expand=True, fill="x")
            ctk.CTkLabel(col, text=texto.upper(), font=fuente(10, "bold"), text_color=TENUE,
                         anchor="w").pack(fill="x")
            self.totales[clave] = ctk.CTkLabel(col, text="0:00:00", font=fuente(13, "bold"),
                                               text_color=TEXTO, anchor="w")
            self.totales[clave].pack(fill="x")

        separador(self).pack(fill="x", padx=16, pady=(12, 0))
        abajo = ctk.CTkFrame(self, fg_color="transparent")
        abajo.pack(fill="x", padx=12, pady=10)
        self.btn = boton(abajo, "▶  Iniciar", lambda: app.alternar_timer(self.nombre), "verde", width=104)
        self.btn.pack(side="left")
        chico = dict(width=10, height=30, font=fuente(12))
        boton(abajo, "Borrar", lambda: app.borrar_timer(self.nombre), "fantasma", **chico).pack(side="right")
        # Solo visible mientras corre: descarta la sesión actual.
        # Mientras corre: "Cancelar" (descarta el tramo). En pausa: "Terminar" (detener del todo).
        self.btn_cancelar = boton(abajo, "Cancelar", lambda: app.accion_secundaria(self.nombre), "fantasma",
                                  text_color=ROJO, **chico)

        # Clic en cualquier parte de la tarjeta (menos los botones) la selecciona.
        self._enlazar_clic(self)

    def _enlazar_clic(self, widget):
        # Solo widgets de CustomTkinter: su .bind ya cubre sus piezas internas de tkinter.
        # Si también se enlazaran esas piezas, un clic contaría doble (y seleccionar + quitar
        # la selección se cancelarían).
        widget.bind("<Button-1>", lambda e: self.app.seleccionar_timer(self.nombre, alternar=True), add="+")
        for hijo in widget.winfo_children():
            if isinstance(hijo, (ctk.CTkFrame, ctk.CTkLabel)):
                self._enlazar_clic(hijo)

    def _poner(self, clave, widget, **kw):
        # Solo reconfigurar si cambió: redibujar es lo caro en CustomTkinter.
        if self._cache.get(clave) != kw:
            self._cache[clave] = kw
            widget.configure(**kw)

    def _mostrar(self, clave, widget, visible, **pack):
        if self._cache.get(clave) != visible:
            self._cache[clave] = visible
            if visible:
                widget.pack(**pack)
            else:
                widget.pack_forget()

    def actualizar(self, corriendo, seleccionado, atajo, actual, hoy, semana, total, pausado=False,
                   en_ventana=False):
        # en_ventana: en pausa solo mientras usas la app; para todo lo demás sigue en marcha.
        self._poner("reloj", self.reloj, text=actual, text_color=VERDE if corriendo else TENUE)
        if en_ventana:
            corriendo, pausado = True, False
        if seleccionado:
            self._poner("borde", self, border_color=VERDE, border_width=2)
        else:
            self._poner("borde", self, border_color=VERDE_BORDE if corriendo else BORDE, border_width=1)
        self._mostrar("marca", self.marca, seleccionado, side="right")
        if not seleccionado:
            texto = "Clic para seleccionar"
        elif atajo:
            texto = f"🎮  {atajo}"
        else:
            texto = "🎮  Asigna el atajo de temporizador →"
        self._poner("mando", self.lbl_mando, text=texto)
        self._mostrar("cancelar", self.btn_cancelar, corriendo or pausado, side="right")
        self._poner("cancelar_txt", self.btn_cancelar, text="Terminar" if pausado else "Cancelar",
                    text_color=TENUE if pausado else ROJO)
        estado = "● EN MARCHA" if corriendo else ("⏸ EN PAUSA" if pausado else "DETENIDO")
        if en_ventana:
            estado = "⏸ PAUSA: USANDO LA APP"
        self._poner("estado", self.estado, text=estado,
                    text_color=VERDE if corriendo and not en_ventana else TENUE)
        if pausado:
            self._poner("btn", self.btn, text="▶  Reanudar", fg_color=TARJETA, hover_color=TARJETA_HOVER,
                        text_color=TEXTO, border_color=BORDE)
        elif corriendo:
            self._poner("btn", self.btn, text="■  Parar", fg_color=ROJO_FONDO, hover_color=ROJO_HOVER,
                        text_color=ROJO, border_color="#5c2433")
        else:
            self._poner("btn", self.btn, text="▶  Iniciar", fg_color=VERDE_FONDO, hover_color=VERDE_HOVER,
                        text_color=VERDE_CLARO, border_color=VERDE_BORDE)
        for clave, valor in (("hoy", hoy), ("semana", semana), ("total", total)):
            self._poner(clave, self.totales[clave], text=valor)


class DialogoRecorte(ctk.CTkToplevel):
    """Elegir dónde empieza y termina una animación y crear su AVIF con esos cuadros.

    Se pueden sacar varios AVIF de la misma grabación (por ejemplo, cada patrón de ataque
    de un jefe): cada uno se guarda como la siguiente foto y el editor sigue abierto.
    """

    TAM_VISTA = (640, 360)

    def __init__(self, app, carpeta):
        super().__init__(app.root, fg_color=PANEL)
        self.app = app
        self.carpeta = Path(carpeta)
        self.cuadros = animacion.cuadros_de(self.carpeta)
        self.fps = int(animacion.info_de(self.carpeta).get("fps_animacion", 60))
        self._pendiente = None
        self._imagen = None
        self._indice_mostrado = 0
        self._creados = []  # (nombre, primer cuadro, último cuadro) de los AVIF de esta vez
        self.title(f"Recortar {self.carpeta.name}")
        self.resizable(False, False)
        self.transient(app.root)
        poner_icono(self)

        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.pack(padx=22, pady=18)
        ctk.CTkLabel(cuerpo, text=self.carpeta.name, font=fuente(16, "bold"), text_color=TEXTO).pack(anchor="w")
        ctk.CTkLabel(cuerpo, text="Mueve el inicio y el final y pulsa «Crear AVIF»: se guarda como la siguiente "
                                  "foto y puedes seguir sacando más animaciones de la misma grabación. "
                                  "Los cuadros que borres de la carpeta tampoco se usan.",
                     font=fuente(12), text_color=TENUE, wraplength=640, justify="left").pack(anchor="w", pady=(2, 10))

        self.vista = ctk.CTkLabel(cuerpo, text="", width=self.TAM_VISTA[0], height=self.TAM_VISTA[1],
                                  fg_color=TARJETA, corner_radius=8)
        self.vista.pack()

        ultimo = max(len(self.cuadros) - 1, 0)
        self.var_inicio = tk.IntVar(value=0)
        self.var_fin = tk.IntVar(value=ultimo)
        self._maximo = ultimo
        self.lbl_inicio = self._fila(cuerpo, "Inicio", self.var_inicio, "inicio")
        self.lbl_fin = self._fila(cuerpo, "Final", self.var_fin, "fin")

        self.lbl_resumen = ctk.CTkLabel(cuerpo, text="", font=fuente(13, "bold"), text_color=VERDE, anchor="w")
        self.lbl_resumen.pack(fill="x", pady=(10, 0))
        self.lbl_creados = ctk.CTkLabel(cuerpo, text="", font=fuente(12), text_color=TENUE, anchor="w",
                                        wraplength=640, justify="left")
        self.lbl_creados.pack(fill="x")

        fila = ctk.CTkFrame(cuerpo, fg_color="transparent")
        fila.pack(fill="x", pady=(14, 0))
        boton(fila, "Abrir carpeta", lambda: abrir(self.carpeta), "fantasma", width=10).pack(side="left")
        boton(fila, "Guardar cuadro como foto", self._guardar_foto, "azul", width=10).pack(side="left", padx=(6, 0))
        boton(fila, "Crear AVIF", self._crear, "verde", width=130).pack(side="right")
        boton(fila, "Cerrar", self.destroy, "normal", width=100).pack(side="right", padx=(0, 8))

        self._actualizar_textos()
        self._mostrar(0)
        self.after(30, self._centrar)

    def _fila(self, padre, texto, var, cual):
        fila = ctk.CTkFrame(padre, fg_color="transparent")
        fila.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(fila, text=texto, font=fuente(12), text_color=TENUE, width=50, anchor="w").pack(side="left")
        self._boton_paso(fila, "−", var, -1, cual).pack(side="left", padx=(4, 0))
        ctk.CTkSlider(fila, from_=0, to=max(self._maximo, 1), number_of_steps=max(self._maximo, 1), variable=var,
                      command=lambda v: self._mover(cual, v), progress_color=VERDE_BORDE, button_color=VERDE,
                      button_hover_color=VERDE_CLARO, fg_color=BORDE).pack(side="left", fill="x", expand=True, padx=8)
        self._boton_paso(fila, "+", var, +1, cual).pack(side="left", padx=(0, 8))
        etiqueta = ctk.CTkLabel(fila, text="", font=fuente(12), text_color=TEXTO, width=150, anchor="e")
        etiqueta.pack(side="left")
        return etiqueta

    def _boton_paso(self, padre, texto, var, paso, cual):
        """Un toque: un cuadro. Mantenido: tras 0.3 s avanza solo, cada vez más rápido."""
        b = boton(padre, texto, None, "normal", width=36, height=32, font=fuente(16, "bold"))
        estado = {"id": None, "intervalo": 90}

        def mover():
            nuevo = min(max(var.get() + paso, 0), self._maximo)
            if nuevo != var.get():
                var.set(nuevo)
                self._mover(cual, nuevo)

        def repetir():
            mover()
            estado["intervalo"] = max(15, int(estado["intervalo"] * 0.85))  # acelera
            estado["id"] = self.after(estado["intervalo"], repetir)

        def presionar(_):
            soltar(None)
            mover()
            estado["intervalo"] = 90
            estado["id"] = self.after(300, repetir)

        def soltar(_):
            if estado["id"]:
                self.after_cancel(estado["id"])
                estado["id"] = None

        b.bind("<ButtonPress-1>", presionar, add="+")
        b.bind("<ButtonRelease-1>", soltar, add="+")
        return b

    def _centrar(self):
        self.update_idletasks()
        r = self.app.root
        x = r.winfo_rootx() + (r.winfo_width() - self.winfo_width()) // 2
        y = r.winfo_rooty() + (r.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _mover(self, cual, valor):
        inicio, fin = self.var_inicio.get(), self.var_fin.get()
        if inicio > fin:  # que el inicio nunca pase al final
            if cual == "inicio":
                self.var_fin.set(inicio)
            else:
                self.var_inicio.set(fin)
        self._actualizar_textos()
        # Mostrar como mucho ~14 cuadros por segundo mientras se arrastra o se mantiene + / −,
        # siempre el más reciente (decodificar cada posición sería lento).
        self._indice_vista = self.var_inicio.get() if cual == "inicio" else self.var_fin.get()
        if not self._pendiente:
            self._pendiente = self.after(70, self._mostrar_pendiente)

    def _mostrar_pendiente(self):
        self._pendiente = None
        self._mostrar(self._indice_vista)

    def _texto_cuadro(self, i):
        return f"cuadro {i + 1} · {i / self.fps:.2f} s"

    def _actualizar_textos(self):
        inicio, fin = self.var_inicio.get(), self.var_fin.get()
        self.lbl_inicio.configure(text=self._texto_cuadro(inicio))
        self.lbl_fin.configure(text=self._texto_cuadro(fin))
        n = fin - inicio + 1 if self.cuadros else 0
        self.lbl_resumen.configure(text=f"{n} cuadros · {n / self.fps:.2f} s")

    def _guardar_foto(self):
        if self.cuadros:
            self.app.guardar_cuadro_como_foto(self.carpeta, self.cuadros[self._indice_mostrado])

    def _mostrar(self, indice):
        self._indice_mostrado = indice
        if not self.cuadros:
            self.vista.configure(text="No hay cuadros en esta carpeta.")
            return
        try:
            with Image.open(self.cuadros[indice]) as img:
                img.draft("RGB", self.TAM_VISTA)
                vista = img.convert("RGB")
            vista.thumbnail(self.TAM_VISTA)
            self._imagen = ctk.CTkImage(vista, size=vista.size)
            self.vista.configure(image=self._imagen, text="")
        except Exception as e:
            self.vista.configure(text=f"No se pudo abrir el cuadro: {e}")

    def _crear(self):
        if not self.cuadros:
            return
        inicio, fin = self.var_inicio.get(), self.var_fin.get()
        destino = self.app.destino_siguiente_foto(self.carpeta, ".avif")
        self.app.crear_avif(self.carpeta, self.cuadros[inicio:fin + 1], destino, self.fps)
        self._creados.append((destino.stem, inicio, fin))
        self.lbl_creados.configure(text="Creados: " + "  ·  ".join(
            f"{nombre} (cuadros {a + 1}–{b + 1})" for nombre, a, b in self._creados))
        # Lo normal es avanzar por la pelea: el siguiente recorte empieza donde terminó este.
        if fin < self._maximo:
            self.var_inicio.set(fin + 1)
            self.var_fin.set(self._maximo)
            self._actualizar_textos()
            self._mostrar(fin + 1)


# --------------------------------------------------------------------------
# Hilo que escucha el mando
# --------------------------------------------------------------------------

class Escucha(threading.Thread):
    """Lee el mando, toma fotos y avisa a la ventana mediante una cola de eventos."""

    def __init__(self, config, eventos):
        super().__init__(daemon=True)
        self.config = config
        self.eventos = eventos
        self.acciones = {}
        self.detector = None
        self._recargar = True
        self._grabar = False
        self._detener = threading.Event()
        self.hay_timer = False  # la ventana lo actualiza: ¿hay algún temporizador en marcha o en pausa?
        self.timer_corriendo = False  # solo en marcha (no en pausa): para el autoshot
        self.en_ventana = False  # el usuario está usando la app: sin autoshot
        self.autoshots = 0
        self.grabador = None    # animación en curso (o guardándose)
        self.grabadores = []    # todas las que aún no terminan de guardarse
        self.guardador = None
        self.pool = None        # procesos que comprimen (así nunca frenan la captura)

    def recargar(self):
        self._recargar = True

    def grabar_combo(self):
        self._grabar = True

    def cancelar_grabacion(self):
        self._grabar = False

    def detener(self):
        self._detener.set()

    def _avisar(self, *evento):
        self.eventos.put(evento)

    @property
    def grabando_animacion(self):
        return self.grabador is not None and self.grabador.grabando

    def detener_animacion(self):
        if self.grabando_animacion:
            self.grabador.detener()

    def ocupado(self):
        """True mientras haya fotos o animaciones pendientes de guardar."""
        self.grabadores = [g for g in self.grabadores if g.ocupado()]
        cola = self.guardador.cola.unfinished_tasks if self.guardador else 0
        return bool(self.grabadores) or cola > 0

    def _sin_timer(self):
        """Aviso sonoro y en pantalla: se intentó capturar sin temporizador en marcha."""
        if self.config.get("sonido_sin_timer", True):
            cap.sonar()  # el sonido de Windows que antes sonaba al tomar foto

    def _autoshot(self, guardador, capturador):
        """Foto automática: misma carpeta y misma numeración que las manuales, sin sonido."""
        try:
            carpeta = cap.carpeta_actual(self.config)
            sufijo = cap.limpiar_sufijo(self.config.get("sufijo"))
            reserva = (carpeta, sufijo, cap.reservar_numero(carpeta, sufijo))
            guardador.cola.put((cap.AUTOSHOT, datetime.now(), capturador.tomar(), reserva))
            self.autoshots += 1
            self._avisar("autoshot", self.autoshots)
            self._avisar("destello")  # el circulito verde: se ve que el autoshot está tomando fotos
        except Exception as e:
            self._avisar("log", f"[!] Autoshot: {e}")

    def _alternar_animacion(self):
        if self.grabando_animacion:
            self.grabador.detener()
            self._avisar("captura", datetime.now())
            return
        if self.config.get("fotos_solo_con_timer", True) and not self.hay_timer:
            self._avisar("log", "Animación ignorada: no hay ningún temporizador en marcha.")
            self._sin_timer()
            return
        try:
            g = animacion.GrabadorAnimacion(self.config, self._avisar, self.pool)
            g.iniciar()
        except Exception as e:
            self._avisar("log", f"[!] No se pudo iniciar la animación: {e}")
            return
        self.grabador = g
        self.grabadores.append(g)
        self._avisar("anim_inicio", g.carpeta)
        self._avisar("captura", datetime.now())

    def _construir_detector(self):
        atajos, acciones = [], {}
        def solo_mando(botones):  # por ahora el teclado no se usa para los atajos
            return [b for b in botones or [] if not cap.es_tecla(b)]
        for a in self.config["atajos"]:
            if solo_mando(a["botones"]):
                clave = f"foto:{a['nombre']}"
                atajos.append({"nombre": clave, "botones": solo_mando(a["botones"])})
                acciones[clave] = ("foto", a["nombre"])
        if solo_mando(self.config.get("atajo_timer")):
            atajos.append({"nombre": "global", "botones": solo_mando(self.config["atajo_timer"])})
            acciones["global"] = ("global", None)
        if solo_mando(self.config.get("atajo_anim")):
            atajos.append({"nombre": "anim", "botones": solo_mando(self.config["atajo_anim"])})
            acciones["anim"] = ("anim", None)
        if solo_mando(self.config.get("atajo_autoshot")):
            atajos.append({"nombre": "autoshot", "botones": solo_mando(self.config["atajo_autoshot"])})
            acciones["autoshot"] = ("autoshot", None)
        self.acciones = acciones
        self.detector = cap.DetectorAtajos(atajos, self.config["espera_entre_fotos"])
        # Solo se revisan las teclas que usa algún atajo (revisar todas cada 8 ms sería un gasto inútil).
        self._vks = set()
        for a in atajos:
            self._vks |= cap.teclas_de(a["botones"])

    def _guardada(self, ruta, img):
        try:
            self._avisar("miniatura", ruta, hacer_miniatura(img))
        except Exception:
            pass

    def run(self):
        try:
            xi = cap.XInput()
        except Exception as e:
            self._avisar("error", f"No se puede leer el mando: {e}")
            return

        teclado = cap.Teclado()
        self._vks = set()
        capturador = None
        try:
            capturador = cap.Capturador(self.config["motor"], self.config["monitor"])
            self._avisar("motor", capturador.nombre_motor)
        except Exception as e:
            self._avisar("error", f"No se pudo preparar la captura de pantalla: {e}")

        self.pool = ProcessPoolExecutor(max_workers=animacion.HILOS["grabacion"],
                                        mp_context=multiprocessing.get_context("spawn"))
        self.pool.submit(trabajador.calentar)  # arranca un proceso desde ya
        guardador = cap.Guardador(self.config, aviso=lambda t: self._avisar("log", t.strip()),
                                  al_guardar=self._guardada, pool=self.pool)
        guardador.start()
        self.guardador = guardador

        conectado = None
        ultimo_estado = 0.0
        estado_grabar = None  # None -> "soltar" -> "acumular"
        acumulado = 0
        proximo_auto = None
        ultimo_error = None
        sin_captura_avisado = False

        while not self._detener.is_set():
            try:
                ahora = time.monotonic()
                m = xi.leer(ahora)

                if ahora - ultimo_estado > 1.0:
                    ultimo_estado = ahora
                    if xi.alguno_conectado() != conectado:
                        conectado = xi.alguno_conectado()
                        self._avisar("mando", conectado)

                if self._grabar:
                    # Espera a que se suelte todo, junta lo que se presione y confirma al soltar.
                    _, esc = teclado.leer_para_asignar()
                    if esc:  # Esc: salir sin asignar (y nunca se puede usar como atajo)
                        self._grabar = False
                        self._recargar = True
                        self._avisar("combo_cancelado")
                        time.sleep(cap.INTERVALO_LECTURA)
                        continue
                    if estado_grabar is None:
                        estado_grabar, acumulado = "soltar", 0
                    if estado_grabar == "soltar":
                        if not m:
                            estado_grabar = "acumular"
                    elif m:
                        acumulado |= m
                    elif acumulado:
                        self._grabar = False
                        self._recargar = True
                        self._avisar("combo", acumulado)
                else:
                    estado_grabar = None
                    if self._recargar:
                        self._recargar = False
                        self._construir_detector()
                        self.detector._anterior = m  # no disparar lo que ya está presionado
                    nombre = self.detector.actualizar(m, ahora)
                    if nombre:
                        tipo, real = self.acciones[nombre]
                        if tipo == "foto":
                            if self.config.get("fotos_solo_con_timer", True) and not self.hay_timer:
                                self._avisar("log", "Foto ignorada: no hay ningún temporizador en marcha.")
                                self._sin_timer()
                            elif self.grabando_animacion:
                                self._avisar("log", "Foto ignorada: se está grabando una animación.")
                            elif capturador is None:
                                self._avisar("log", "[!] La captura de pantalla no está disponible.")
                            else:
                                try:
                                    # El número se aparta al presionar, así fotos y animaciones siguen el orden.
                                    carpeta = cap.carpeta_actual(self.config)
                                    sufijo = cap.limpiar_sufijo(self.config.get("sufijo"))
                                    reserva = (carpeta, sufijo, cap.reservar_numero(carpeta, sufijo))
                                    guardador.cola.put((real, datetime.now(), capturador.tomar(), reserva))
                                    self._avisar("captura", datetime.now())
                                    self._avisar("destello")
                                except Exception as e:
                                    self._avisar("log", f"[!] No se pudo tomar la foto: {e}")
                        elif tipo == "global":
                            self._avisar("timer_global", datetime.now())
                        elif tipo == "anim":
                            self._alternar_animacion()
                        elif tipo == "autoshot":
                            self._avisar("autoshot_alternar")

                # Autoshot: una foto cada N segundos mientras corre un temporizador (no en pausa).
                permitido = self.timer_corriendo or not self.config.get("fotos_solo_con_timer", True)
                if self.config.get("autoshot") and permitido and capturador is None and not sin_captura_avisado:
                    sin_captura_avisado = True
                    self._avisar("log", "[!] Autoshot: la captura de pantalla no está disponible.")
                if (self.config.get("autoshot") and permitido and capturador is not None
                        and not self.grabando_animacion and not self._grabar and not self.en_ventana):
                    intervalo = max(1.0, float(self.config.get("autoshot_seg", 3)))
                    if proximo_auto is None:
                        proximo_auto = ahora + intervalo  # la primera, un intervalo después de activarlo
                    elif ahora >= proximo_auto:
                        proximo_auto = ahora + intervalo
                        self._autoshot(guardador, capturador)
                else:
                    proximo_auto = None

            except Exception:
                # Nunca dejar de escuchar el mando por un error: se anota y se sigue.
                detalle = traceback.format_exc()
                if detalle != ultimo_error:
                    ultimo_error = detalle
                    registrar_error(detalle)
                    self._avisar("log", f"[!] Error al leer los atajos: {detalle.strip().splitlines()[-1]} "
                                        f"(detalles en {LOG_ERRORES.name})")

            time.sleep(cap.INTERVALO_LECTURA)

        self.detener_animacion()
        guardador.cola.join()
        self.pool.shutdown(wait=True)


# --------------------------------------------------------------------------
# Ventana
# --------------------------------------------------------------------------

class App:
    def __init__(self, root):
        self.root = root
        self._migrado_de = cap.migrar_datos()  # carpeta vieja (capturador_silksong) -> esta
        self.config = cap.cargar_config()
        self.config.setdefault("pitido_timers", False)
        self.config.setdefault("fotos_solo_con_timer", True)
        self.config.setdefault("timer_seleccionado", None)
        self.config.setdefault("sonido_anim", True)
        self.config.setdefault("sonido_sin_timer", True)
        if "pausa_auto_seg" not in self.config:  # antes era en minutos; ahora 30 s por defecto
            self.config["pausa_auto_seg"] = 30 if self.config.pop("pausa_auto_min", 5) else 0
        self.config.setdefault("avisos_pantalla", True)
        self.config.setdefault("volumen", 3)
        self.config.setdefault("autoshot", False)
        self.config.setdefault("autoshot_seg", 3)
        sonidos.volumen = self.config["volumen"]
        self._ultima_foto = {}  # temporizador -> última foto/animación de la sesión
        self._pausados_por_foco = set()  # en pausa solo mientras se usa la ventana
        self.config.setdefault("anim_fps", 60)
        if self.config.get("version_config", 1) < 2:
            # Desde esta versión el AVIF se crea después de recortar, no al terminar de grabar.
            self.config["anim_guardar"] = "cuadros"
            self.config["version_config"] = 2
        self.config.setdefault("anim_guardar", "cuadros")
        self.config["sufijo"] = cap.limpiar_sufijo(self.config.get("sufijo"))
        self._sin_teclas = self._quitar_teclas()
        self._grabando_desde = None
        self._migrar_botones_propios()
        self._ultimo_tick = datetime.now()
        cap.aplicar_prioridad(self.config["prioridad"])
        self.registro = RegistroTiempos(CARPETA)
        self.eventos = queue.Queue()
        self.escucha = Escucha(self.config, self.eventos)
        self.escucha_error = None
        self._al_grabar = None
        self._dialogo_grabar = None
        self.tarjetas = {}
        self.miniaturas = []  # [(ruta, PIL.Image)] más reciente primero
        # Se crean antes que la interfaz porque el primer refresco ya los usa.
        self.aviso = AvisoPantalla(root)
        self.bandeja = bandeja.Bandeja(self.eventos, TITULO) if os.name == "nt" else None
        self._evento_mostrar = crear_evento_mostrar()

        root.title(TITULO)
        ancho = min(1560, root.winfo_screenwidth() - 80)
        alto = min(900, root.winfo_screenheight() - 120)
        root.geometry(f"{max(ancho, 1100)}x{max(alto, 640)}")
        root.minsize(1100, 640)
        root.configure(fg_color=FONDO)
        poner_icono(root)

        self._construir_ui()
        self._refrescar_fotos()
        self._refrescar_global()
        self._refrescar_timers()

        if self.registro.recuperadas:
            lineas = [f"• {a}: {formato_duracion(d.total_seconds())}" for a, d in self.registro.recuperadas]
            for linea in lineas:
                self.log(f"Recuperado de un cierre inesperado {linea[2:]}")
            root.after(600, lambda: Dialogo.mostrar(
                root, "Tiempo recuperado",
                "La app se cerró sin detener estos temporizadores. Se guardaron hasta el último "
                "momento registrado:\n\n" + "\n".join(lineas)))

        self.log(f"Capturador v{cap.VERSION}")
        if self._migrado_de:
            self.log(f"Se copiaron tu configuración y tus tiempos desde {self._migrado_de}")
        if self._sin_teclas:
            self._guardar()
            self.log("Los atajos ahora son solo del mando; se quitaron las teclas de: " + ", ".join(self._sin_teclas))
        if not self.aviso.disponible:
            self.log(f"Indicador en pantalla desactivado: {self.aviso.motivo}")
        if self.bandeja is not None and not self.bandeja.disponible:
            self.log(f"Sin icono en la bandeja: {self.bandeja.error}")
            self.bandeja = None

        self.escucha.start()
        root.protocol("WM_DELETE_WINDOW", self.cerrar)
        root.after(100, self._procesar_eventos)
        root.after(500, self._refrescar_tiempos)
        root.after(LATIDO_CADA_MS, self._latido)

    def _migrar_botones_propios(self):
        """Antes cada temporizador tenía su botón; ahora hay un solo atajo para todos."""
        propios = [b for b in (t.pop("botones", None) for t in self.config["timers"]) if b]
        if propios:
            # El primero que existía pasa a ser el atajo para todos (si no había uno).
            self.config.setdefault("atajo_timer", propios[0])
            cap.guardar_config(self.config)

    # ------------------------------------------------------------------ UI

    def _construir_ui(self):
        r = self.root
        r.grid_columnconfigure(1, weight=1)
        r.grid_rowconfigure(1, weight=1)

        # ---- Encabezado
        enc = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0, height=64)
        enc.grid(row=0, column=0, columnspan=3, sticky="ew")
        enc.grid_propagate(False)
        enc.grid_columnconfigure(3, weight=1)

        logo = ctk.CTkFrame(enc, fg_color="transparent")
        logo.grid(row=0, column=0, padx=(20, 0), pady=12)
        if ICONO.exists():
            img = Image.open(ICONO)
            img.size  # carga el tamaño más grande del .ico
            ctk.CTkLabel(logo, text="", image=ctk.CTkImage(img, size=(32, 32))).pack(side="left")
        titulos = ctk.CTkFrame(logo, fg_color="transparent")
        titulos.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(titulos, text="Capturador", font=fuente(15, "bold"), text_color=TEXTO,
                     height=18).pack(anchor="w")
        ctk.CTkLabel(titulos, text=f"Fotos y tiempos · v{cap.VERSION}", font=fuente(11), text_color=TENUE,
                     height=14).pack(anchor="w")

        ctk.CTkFrame(enc, width=1, height=30, fg_color=BORDE).grid(row=0, column=1, padx=16)
        ctk.CTkLabel(enc, text="Apps / Capturador", font=fuente(12), text_color=TENUE).grid(row=0, column=2)

        derecha = ctk.CTkFrame(enc, fg_color="transparent")
        derecha.grid(row=0, column=4, padx=20)
        ctk.CTkLabel(derecha, text="Prioridad", font=fuente(12), text_color=TENUE).pack(side="left", padx=(0, 8))
        self.seg_prioridad = ctk.CTkSegmentedButton(
            derecha, values=["Juego", "Grabación"], command=self._cambiar_prioridad, height=30, corner_radius=8,
            font=fuente(12, "bold"), fg_color=TARJETA, selected_color=VERDE_FONDO, selected_hover_color=VERDE_HOVER,
            unselected_color=TARJETA, unselected_hover_color=TARJETA_HOVER, text_color=TEXTO)
        self.seg_prioridad.set("Grabación" if self.config["prioridad"] == "grabacion" else "Juego")
        self.seg_prioridad.pack(side="left", padx=(0, 16))
        self.pastilla_mando = ctk.CTkLabel(derecha, text="●  Buscando mando…", font=fuente(12, "bold"),
                                           text_color=TENUE, fg_color=TARJETA, corner_radius=14,
                                           height=30, padx=12)
        self.pastilla_mando.pack(side="left", padx=(0, 14))
        self.pastilla_rec = ctk.CTkLabel(derecha, text="", font=fuente(12, "bold"), text_color=ROJO,
                                         fg_color=ROJO_FONDO, corner_radius=14, height=30, padx=12)
        boton(derecha, "Abrir fotos", self.abrir_fotos, "verde", width=120).pack(side="left", padx=(0, 8))
        boton(derecha, "Historial", self.abrir_historial, "azul", width=110).pack(side="left")

        separador(r).grid(row=0, column=0, columnspan=3, sticky="sew")

        # ---- Barra izquierda: fotos recientes
        izq = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0, width=290)
        izq.grid(row=1, column=0, sticky="ns")
        izq.grid_propagate(False)
        izq.grid_rowconfigure(4, weight=1)
        izq.grid_columnconfigure(0, weight=1)

        barra = ctk.CTkFrame(izq, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 4))
        boton(barra, "📁", self.elegir_carpeta, "normal", width=38).pack(side="left")
        self.lbl_carpeta_nombre = ctk.CTkLabel(barra, text="", font=fuente(13, "bold"), text_color=TEXTO,
                                               fg_color=TARJETA, corner_radius=8, height=34, anchor="w",
                                               padx=12)
        self.lbl_carpeta_nombre.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.ins_fotos = insignia(barra, "0")
        self.ins_fotos.pack(side="left")

        dueno = ctk.CTkFrame(izq, fg_color="transparent")
        dueno.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.lbl_dueno = ctk.CTkLabel(dueno, text="", font=fuente(11), text_color=TENUE, anchor="w", height=24)
        self.lbl_dueno.pack(side="left")
        self.btn_general = boton(dueno, "Usar general", self.usar_carpeta_general, "fantasma",
                                 width=10, height=24, font=fuente(11))

        suf = ctk.CTkFrame(izq, fg_color="transparent")
        suf.grid(row=2, column=0, sticky="ew", padx=14)
        ctk.CTkLabel(suf, text="Sufijo", font=fuente(12), text_color=TENUE).pack(side="left", padx=(2, 8))
        self.var_sufijo = tk.StringVar(value=cap.limpiar_sufijo(self.config.get("sufijo")))
        ctk.CTkEntry(suf, textvariable=self.var_sufijo, height=32, fg_color=TARJETA, border_color=BORDE,
                     text_color=TEXTO, font=fuente(13)).pack(side="left", fill="x", expand=True)
        self.lbl_ejemplo = ctk.CTkLabel(izq, text="", font=fuente(10), text_color=TENUE, anchor="w")
        self.lbl_ejemplo.grid(row=3, column=0, sticky="ew", padx=18, pady=(2, 8))
        self.var_sufijo.trace_add("write", lambda *a: self._sufijo_cambiado())

        self.grilla_fotos = ctk.CTkScrollableFrame(izq, fg_color="transparent", scrollbar_button_color=BORDE,
                                                   scrollbar_button_hover_color=TENUE)
        self.grilla_fotos.grid(row=4, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        self._sufijo_cambiado()
        self.grilla_fotos.grid_columnconfigure((0, 1), weight=1, uniform="foto")

        ctk.CTkFrame(r, width=1, fg_color=BORDE, corner_radius=0).grid(row=1, column=0, sticky="nse")

        # ---- Centro: temporizadores
        centro = ctk.CTkFrame(r, fg_color=FONDO, corner_radius=0)
        centro.grid(row=1, column=1, sticky="nsew")
        centro.grid_columnconfigure(0, weight=1)
        centro.grid_rowconfigure(2, weight=1)

        cab, self.ins_activos = titulo_seccion(centro, "Temporizadores", "0 activos")
        cab.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 2))
        ctk.CTkLabel(centro, text="Clic en una tarjeta para seleccionarla (otro clic la quita). El atajo inicia y para la seleccionada. "
                                  "Mientras usas esta ventana, el tiempo y el autoshot se pausan.",
                     font=fuente(12), text_color=TENUE, anchor="w", justify="left",
                     wraplength=620).grid(row=1, column=0, sticky="ew", padx=28)

        self.grilla_timers = ctk.CTkScrollableFrame(centro, fg_color="transparent",
                                                    scrollbar_button_color=BORDE,
                                                    scrollbar_button_hover_color=TENUE)
        self.grilla_timers.grid(row=2, column=0, sticky="nsew", padx=18, pady=(12, 0))
        self._columnas_timers = 2
        self.grilla_timers.bind("<Configure>", self._ajustar_columnas, add="+")

        boton(centro, "+  Temporizador", self.nuevo_timer, "normal", anchor="w",
              font=fuente(13)).grid(row=3, column=0, sticky="ew", padx=28, pady=(8, 18))

        ctk.CTkFrame(r, width=1, fg_color=BORDE, corner_radius=0).grid(row=1, column=2, sticky="nsw")

        # ---- Panel derecho: atajos y ajustes
        der = ctk.CTkScrollableFrame(r, fg_color=PANEL, corner_radius=0, width=310,
                                     scrollbar_button_color=BORDE, scrollbar_button_hover_color=TENUE)
        der.grid(row=1, column=2, sticky="ns")
        pad = dict(padx=20, fill="x")

        def interruptor(texto, var):
            return ctk.CTkSwitch(der, text=texto, variable=var, command=self._guardar_ajustes, font=fuente(13),
                                 text_color=TEXTO, fg_color=BORDE, progress_color=VERDE_BORDE,
                                 button_color=TEXTO, button_hover_color="#ffffff")

        # Fotos
        cab, self.ins_atajos = titulo_seccion(der, "Atajos de foto", "0")
        cab.pack(pady=(18, 10), **pad)
        self.lista_atajos = ctk.CTkFrame(der, fg_color="transparent")
        self.lista_atajos.pack(**pad)
        self.lista_atajos.grid_columnconfigure(0, weight=1)
        boton(der, "+  Atajo de foto", self.agregar_foto, "normal", anchor="w",
              font=fuente(13)).pack(pady=(8, 10), **pad)
        # Autoshot: foto automática cada N segundos
        fila_auto = ctk.CTkFrame(der, fg_color="transparent")
        fila_auto.pack(pady=(8, 0), **pad)
        self.var_autoshot = tk.BooleanVar(value=self.config["autoshot"])
        ctk.CTkSwitch(fila_auto, text="Autoshot", variable=self.var_autoshot, command=self._cambiar_autoshot,
                      font=fuente(13), text_color=TEXTO, fg_color=BORDE, progress_color=VERDE_BORDE,
                      button_color=TEXTO, button_hover_color="#ffffff").pack(side="left")
        boton(fila_auto, "+", lambda: self._paso_autoshot(+1), "normal", width=32, height=30,
              font=fuente(15, "bold")).pack(side="right")
        self.lbl_autoshot_seg = ctk.CTkLabel(fila_auto, text="", font=fuente(13, "bold"), text_color=TEXTO, width=44)
        self.lbl_autoshot_seg.pack(side="right")
        boton(fila_auto, "−", lambda: self._paso_autoshot(-1), "normal", width=32, height=30,
              font=fuente(15, "bold")).pack(side="right")
        self.lbl_autoshot = ctk.CTkLabel(der, text="", font=fuente(11), text_color=TENUE, anchor="w",
                                         wraplength=270, justify="left")
        self.lbl_autoshot.pack(pady=(2, 0), **pad)
        self._mostrar_autoshot()
        ctk.CTkLabel(der, text="Atajo para prender / apagar el autoshot", font=fuente(12), text_color=TENUE,
                     anchor="w").pack(pady=(10, 4), **pad)
        self.fila_autoshot = ctk.CTkFrame(der, fg_color=TARJETA, corner_radius=10, border_width=1,
                                          border_color=BORDE)
        self.fila_autoshot.pack(**pad)

        separador(der).pack(pady=20, **pad)

        # Atajo global de temporizador
        cab, _ = titulo_seccion(der, "Atajo de temporizador", "Todos")
        cab.pack(pady=(0, 4), **pad)
        ctk.CTkLabel(der, text="Inicia o para el temporizador seleccionado.", font=fuente(12),
                     text_color=TENUE, anchor="w").pack(pady=(0, 8), **pad)
        self.fila_global = ctk.CTkFrame(der, fg_color=TARJETA, corner_radius=10, border_width=1,
                                        border_color=BORDE)
        self.fila_global.pack(**pad)

        separador(der).pack(pady=20, **pad)

        cab, _ = titulo_seccion(der, "Atajo de animación", f"{self.config['anim_fps']} fps")
        cab.pack(pady=(0, 4), **pad)
        ctk.CTkLabel(der, text="Una vez para grabar, otra para terminar.", font=fuente(12),
                     text_color=TENUE, anchor="w").pack(pady=(0, 8), **pad)
        self.fila_anim = ctk.CTkFrame(der, fg_color=TARJETA, corner_radius=10, border_width=1,
                                      border_color=BORDE)
        self.fila_anim.pack(**pad)
        ctk.CTkLabel(der, text="Guardar como", font=fuente(12), text_color=TENUE, anchor="w").pack(pady=(12, 4), **pad)
        nombres_salida = {"cuadros": "Cuadros", "ambos": "Ambos", "avif": "AVIF animado"}
        self.seg_salida = ctk.CTkSegmentedButton(
            der, values=list(nombres_salida.values()), height=34, corner_radius=8, font=fuente(12),
            command=lambda v: self._cambiar_salida({n: k for k, n in nombres_salida.items()}[v]),
            fg_color=TARJETA, selected_color=SELECCION, selected_hover_color=SELECCION,
            unselected_color=TARJETA, unselected_hover_color=TARJETA_HOVER, text_color=TEXTO)
        self.seg_salida.set(nombres_salida.get(self.config["anim_guardar"], "Cuadros"))
        self.seg_salida.pack(**pad)
        ctk.CTkLabel(der, text="Con «Cuadros», haz clic en la animación para recortarla y crear el AVIF.",
                     font=fuente(11), text_color=TENUE, anchor="w", wraplength=270, justify="left").pack(pady=(6, 0), **pad)
        boton(der, "Recortar carpeta de cuadros…", self.recortar_carpeta, "normal",
              height=36).pack(pady=(10, 0), **pad)

        separador(der).pack(pady=20, **pad)

        cab, _ = titulo_seccion(der, "Formato", "Fotos")
        cab.pack(pady=(0, 10), **pad)
        self.seg_formato = ctk.CTkSegmentedButton(
            der, values=["PNG", "JPG", "WEBP"], command=self._cambiar_formato, height=36, corner_radius=8,
            font=fuente(13), fg_color=TARJETA, selected_color=SELECCION, selected_hover_color=SELECCION,
            unselected_color=TARJETA, unselected_hover_color=TARJETA_HOVER, text_color=TEXTO)
        self.seg_formato.set(cap.extension(self.config["formato"]).upper())
        self.seg_formato.pack(**pad)

        ctk.CTkLabel(der, text="Resolución", font=fuente(12), text_color=TENUE, anchor="w").pack(pady=(16, 4), **pad)
        self.seg_resolucion = ctk.CTkSegmentedButton(
            der, values=["Nativa", "720p"], command=self._cambiar_resolucion, height=36, corner_radius=8,
            font=fuente(13), fg_color=TARJETA, selected_color=SELECCION, selected_hover_color=SELECCION,
            unselected_color=TARJETA, unselected_hover_color=TARJETA_HOVER, text_color=TEXTO)
        self.seg_resolucion.set("720p" if self.config["resolucion"] == "720p" else "Nativa")
        self.seg_resolucion.pack(**pad)

        separador(der).pack(pady=20, **pad)

        cab, _ = titulo_seccion(der, "Más opciones")
        cab.pack(pady=(0, 6), **pad)
        self.var_solo_timer = tk.BooleanVar(value=self.config["fotos_solo_con_timer"])
        interruptor("Capturar solo con temporizador", self.var_solo_timer).pack(pady=5, **pad)
        ctk.CTkLabel(der, text="Pausa automática sin fotos", font=fuente(12), text_color=TENUE,
                     anchor="w").pack(pady=(12, 4), **pad)
        opciones_pausa = {"No": 0, "30 s": 30, "1 min": 60, "3 min": 180, "5 min": 300}
        self.seg_pausa = ctk.CTkSegmentedButton(
            der, values=list(opciones_pausa), height=34, corner_radius=8, font=fuente(12),
            command=lambda v: self._cambiar_pausa(opciones_pausa[v]),
            fg_color=TARJETA, selected_color=SELECCION, selected_hover_color=SELECCION,
            unselected_color=TARJETA, unselected_hover_color=TARJETA_HOVER, text_color=TEXTO)
        self.seg_pausa.set(next((k for k, v in opciones_pausa.items() if v == self.config["pausa_auto_seg"]), "30 s"))
        self.seg_pausa.pack(**pad)
        ctk.CTkLabel(der, text="Carpeta general", font=fuente(12), text_color=TENUE, anchor="w").pack(pady=(16, 4), **pad)
        fila = ctk.CTkFrame(der, fg_color="transparent")
        fila.pack(**pad)
        self.lbl_carpeta = ctk.CTkLabel(fila, text="", font=fuente(12), text_color=TEXTO, fg_color=TARJETA,
                                        corner_radius=8, height=36, anchor="w", padx=12)
        boton(fila, "Cambiar", self.cambiar_carpeta, "normal", width=84, height=36).pack(side="right", padx=(8, 0))
        self.lbl_carpeta.pack(side="left", fill="x", expand=True)
        self._mostrar_carpeta()

        separador(der).pack(pady=20, **pad)

        cab, _ = titulo_seccion(der, "Sonidos")
        cab.pack(pady=(0, 6), **pad)
        fila_vol = ctk.CTkFrame(der, fg_color="transparent")
        fila_vol.pack(pady=(4, 8), **pad)
        ctk.CTkLabel(fila_vol, text="Volumen", font=fuente(13), text_color=TEXTO).pack(side="left")
        self.lbl_volumen = ctk.CTkLabel(fila_vol, text=f"{self.config['volumen']}/5", font=fuente(12),
                                        text_color=TENUE, width=34)
        self.lbl_volumen.pack(side="right")
        BarraVolumen(fila_vol, self.config["volumen"], self._cambiar_volumen).pack(side="right", padx=(0, 8))
        self.var_sonido = tk.BooleanVar(value=self.config["sonido"])
        self.var_pitido = tk.BooleanVar(value=self.config["pitido_timers"])
        interruptor("Sonido al tomar foto", self.var_sonido).pack(pady=5, **pad)
        interruptor("Pitido al iniciar/parar con el mando", self.var_pitido).pack(pady=5, **pad)
        self.var_sonido_anim = tk.BooleanVar(value=self.config["sonido_anim"])
        interruptor("Sonido al grabar animación", self.var_sonido_anim).pack(pady=5, **pad)
        self.var_sonido_sin_timer = tk.BooleanVar(value=self.config["sonido_sin_timer"])
        interruptor("Aviso si no hay temporizador", self.var_sonido_sin_timer).pack(pady=5, **pad)
        self.var_avisos = tk.BooleanVar(value=self.config["avisos_pantalla"])
        interruptor("Indicador en pantalla", self.var_avisos).pack(pady=5, **pad)
        self.var_inicio = tk.BooleanVar(value=bandeja.inicio_con_windows())
        ctk.CTkSwitch(der, text="Iniciar con Windows", variable=self.var_inicio,
                      command=self._cambiar_inicio_windows, font=fuente(13), text_color=TEXTO, fg_color=BORDE,
                      progress_color=VERDE_BORDE, button_color=TEXTO,
                      button_hover_color="#ffffff").pack(pady=5, **pad)

        separador(der).pack(pady=20, **pad)

        cab, _ = titulo_seccion(der, "Actividad", "Sesión")
        cab.pack(pady=(0, 10), **pad)
        self.txt_log = ctk.CTkTextbox(der, height=190, fg_color=TARJETA, border_color=BORDE, border_width=1,
                                      corner_radius=10, text_color=TEXTO, font=fuente(11, familia=MONO),
                                      wrap="word", scrollbar_button_color=BORDE)
        self.txt_log.pack(pady=(0, 20), **pad)
        self.txt_log.configure(state="disabled")

        # ---- Barra de estado
        pie = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0, height=30)
        pie.grid(row=2, column=0, columnspan=3, sticky="ew")
        separador(pie).place(relx=0, rely=0, relwidth=1)
        self.lbl_estado = ctk.CTkLabel(pie, text="Capturador  ·  Listo", font=fuente(11), text_color=TENUE)
        self.lbl_estado.pack(side="left", padx=16)
        self.lbl_motor = ctk.CTkLabel(pie, text="Capturador", font=fuente(11), text_color=TENUE)
        self.lbl_motor.pack(side="right", padx=16)

    # ------------------------------------------------------------------ util

    def log(self, texto):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"{datetime.now():%H:%M:%S}  {texto}\n")
        lineas = int(self.txt_log.index("end-1c").split(".")[0])
        if lineas > 200:
            self.txt_log.delete("1.0", f"{lineas - 200}.0")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")
        self.lbl_estado.configure(text=f"Capturador  ·  {texto}")

    def _guardar(self):
        cap.guardar_config(self.config)

    def _guardar_ajustes(self):
        self.config["sonido"] = self.var_sonido.get()
        self.config["pitido_timers"] = self.var_pitido.get()
        self.config["fotos_solo_con_timer"] = self.var_solo_timer.get()
        self.config["sonido_anim"] = self.var_sonido_anim.get()
        self.config["sonido_sin_timer"] = self.var_sonido_sin_timer.get()
        self.config["avisos_pantalla"] = self.var_avisos.get()
        self._actualizar_indicador()
        self._guardar()

    def _mostrar_autoshot(self, cuantas=None):
        self.lbl_autoshot_seg.configure(text=f"{self.config['autoshot_seg']} s")
        if not self.config["autoshot"]:
            texto = "Una foto cada tantos segundos mientras corre el temporizador, junto a las demás."
        elif cuantas:
            texto = f"Activo · {cuantas} fotos automáticas"
        else:
            texto = "Activo · las fotos van junto a las demás, con la misma numeración"
        self.lbl_autoshot.configure(text=texto, text_color=VERDE if self.config["autoshot"] else TENUE)

    def _cambiar_autoshot(self):
        self.config["autoshot"] = self.var_autoshot.get()
        self._guardar()
        if self.config["autoshot"]:
            self.escucha.autoshots = 0
            self.log(f"Autoshot activado: una foto cada {self.config['autoshot_seg']} s mientras corre el temporizador.")
        else:
            self.log(f"Autoshot desactivado ({self.escucha.autoshots} fotos automáticas).")
        self._mostrar_autoshot()

    def _paso_autoshot(self, paso):
        self.config["autoshot_seg"] = min(60, max(1, int(self.config["autoshot_seg"]) + paso))
        self._guardar()
        self._mostrar_autoshot(self.escucha.autoshots if self.config["autoshot"] else None)

    def _cambiar_volumen(self, nivel):
        self.config["volumen"] = nivel
        sonidos.volumen = nivel
        self.lbl_volumen.configure(text=f"{nivel}/5")
        self._guardar()
        sonidos.reproducir("timer_inicio")  # para escuchar cómo queda

    def _cambiar_inicio_windows(self):
        activar = self.var_inicio.get()
        try:
            bandeja.activar_inicio_con_windows(activar)
            self.log("Se abrirá al iniciar Windows, en la bandeja junto al reloj." if activar
                     else "Ya no se abrirá al iniciar Windows.")
        except Exception as e:
            self.var_inicio.set(not activar)
            self.log(f"[!] No se pudo cambiar el inicio con Windows: {e}")

    def mostrar_ventana(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _cambiar_pausa(self, segundos):
        self.config["pausa_auto_seg"] = segundos
        self._guardar()
        if segundos:
            self.log(f"Pausa automática: tras {texto_espera(segundos)} sin fotos (cuenta hasta la última foto).")
        else:
            self.log("Pausa automática desactivada.")

    def _cambiar_salida(self, salida):
        self.config["anim_guardar"] = salida
        self._guardar()
        textos = {"avif": "un solo archivo .avif animado junto a las fotos",
                  "cuadros": "una carpeta con cada cuadro",
                  "ambos": "la carpeta de cuadros con el .avif animado adentro"}
        self.log(f"Las animaciones se guardarán como {textos[salida]}.")
        if salida != "cuadros" and not animacion.avif_disponible():
            self.log("[!] Tu Pillow no tiene AVIF: ejecuta instalar.bat para actualizarlo.")

    def _cambiar_resolucion(self, valor):
        self.config["resolucion"] = "720p" if valor == "720p" else "nativa"
        self._guardar()
        self.log(f"Resolución: {valor} (las animaciones en curso conservan la suya)")

    def _cambiar_prioridad(self, valor):
        modo = "grabacion" if valor == "Grabación" else "juego"
        self.config["prioridad"] = modo
        cap.aplicar_prioridad(modo)
        self._guardar()
        if modo == "juego":
            self.log("Prioridad: juego. Se guarda con calma para no quitarle fluidez.")
        else:
            self.log("Prioridad: grabación. Se guarda lo más rápido posible; el juego puede ir algo más lento.")

    def _cambiar_formato(self, valor):
        self.config["formato"] = valor.lower()
        self._guardar()
        self._sufijo_cambiado()  # actualizar el ejemplo de nombre

    def _mostrar_carpeta(self):
        """Panel derecho: carpeta general. Barra izquierda: la que se usa ahora."""
        self.lbl_carpeta.configure(text=ruta_corta(self.config["carpeta"], 26))
        actual = cap.carpeta_actual(self.config)
        self.lbl_carpeta_nombre.configure(text=actual.name or str(actual))
        timer = self._timer(self.config.get("timer_seleccionado"))
        propia = bool(timer and timer.get("carpeta"))
        if propia:
            self.lbl_dueno.configure(text=f"Carpeta de «{timer['nombre']}»", text_color=VERDE)
            self.btn_general.pack(side="right")
        else:
            self.lbl_dueno.configure(text="Carpeta general", text_color=TENUE)
            self.btn_general.pack_forget()
        # Si cambió la carpeta en uso, cargar sus miniaturas.
        if actual != getattr(self, "_carpeta_mostrada", None):
            self._carpeta_mostrada = actual
            self.miniaturas = []
            self._total_fotos = 0
            self._dibujar_miniaturas()
            threading.Thread(target=self._cargar_miniaturas, args=(actual,), daemon=True).start()

    def _timer(self, nombre):
        return next((t for t in self.config["timers"] if t["nombre"] == nombre), None)

    def _en_carpeta_mostrada(self, ruta):
        return self._carpeta_mostrada in Path(ruta).parents

    def _refrescar_fotos(self):
        for w in self.lista_atajos.winfo_children():
            w.destroy()
        for i, a in enumerate(self.config["atajos"]):
            fila = ctk.CTkFrame(self.lista_atajos, fg_color=TARJETA, corner_radius=10, border_width=1,
                                border_color=BORDE)
            fila.grid(row=i, column=0, sticky="ew", pady=4)
            ctk.CTkLabel(fila, text=a["nombre"], font=fuente(13, "bold"), text_color=TEXTO).pack(
                side="left", padx=(14, 8), pady=10)
            boton(fila, "✕", lambda n=a["nombre"]: self.borrar_foto(n), "fantasma", width=30,
                  height=28).pack(side="right", padx=(0, 8))
            insignia(fila, cap.texto_combo(a["botones"]), color=VERDE, borde=VERDE_BORDE).pack(side="right")
        if not self.config["atajos"]:
            ctk.CTkLabel(self.lista_atajos, text="Todavía no hay atajos.", font=fuente(12),
                         text_color=TENUE, anchor="w").grid(row=0, column=0, sticky="ew")
        self.ins_atajos.configure(text=str(len(self.config["atajos"])))

    def _refrescar_timers(self):
        nombres = [t["nombre"] for t in self.config["timers"]]
        if self.config["timer_seleccionado"] not in nombres + [None]:
            self.config["timer_seleccionado"] = None  # se borró el que estaba seleccionado
            self._guardar()
            self._mostrar_carpeta()
        for w in self.grilla_timers.winfo_children():
            w.destroy()
        self.tarjetas = {}
        for t in self.config["timers"]:
            self.tarjetas[t["nombre"]] = TarjetaTimer(self.grilla_timers, self, t)
        self._colocar_tarjetas()
        if not self.config["timers"]:
            vacio = ctk.CTkFrame(self.grilla_timers, fg_color=TARJETA, corner_radius=12, border_width=1,
                                 border_color=BORDE)
            vacio.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
            ctk.CTkLabel(vacio, text="Crea tu primer temporizador (por ejemplo «escribir» o «fotos»).",
                         font=fuente(13), text_color=TENUE).pack(pady=28)
        self._refrescar_tiempos(reprogramar=False)

    def _ajustar_columnas(self, evento):
        # Dos columnas solo si cada tarjeta queda con espacio para todos sus botones.
        columnas = 2 if evento.width >= 760 else 1
        if columnas != self._columnas_timers:
            self._columnas_timers = columnas
            self._colocar_tarjetas()

    def _colocar_tarjetas(self):
        cols = self._columnas_timers
        for c in range(2):
            self.grilla_timers.grid_columnconfigure(c, weight=1 if c < cols else 0,
                                                    uniform="timer" if c < cols else "")
        for i, tarjeta in enumerate(self.tarjetas.values()):
            tarjeta.grid(row=i // cols, column=i % cols, sticky="nsew", padx=10, pady=10)

    def _refrescar_tiempos(self, reprogramar=True):
        ahora = datetime.now()
        if self.registro.en_curso and (ahora - self._ultimo_tick).total_seconds() > SALTO_SUSPENSION_SEG:
            for nombre, duracion in self.registro.parar_todos(self._ultimo_tick).items():
                self.log(f"■ '{nombre}' detenido por suspensión de la PC: "
                         f"{formato_duracion(duracion.total_seconds())}")
        self._ultimo_tick = ahora
        self._pausa_por_ventana(ahora)
        self._revisar_pausa_automatica(ahora)
        self._actualizar_indicador()
        # Se puede tomar foto con un temporizador en marcha o en pausa (la foto lo reanuda).
        self.escucha.hay_timer = bool(self.registro.en_curso or self.registro.pausados)
        self.escucha.timer_corriendo = bool(self.registro.en_curso)

        en_marcha = []
        atajo = cap.texto_combo(self.config["atajo_timer"]) if self.config.get("atajo_timer") else None
        for nombre, tarjeta in self.tarjetas.items():
            corriendo = self.registro.corriendo(nombre)
            pausado = self.registro.en_pausa(nombre)
            actual = formato_duracion(self.registro.sesion(nombre, ahora))
            tarjeta.actualizar(
                corriendo, nombre == self.config["timer_seleccionado"], atajo, actual,
                formato_duracion(self.registro.total_hoy(nombre, ahora)),
                formato_duracion(self.registro.total_semana(nombre, ahora)),
                formato_duracion(self.registro.total(nombre, ahora=ahora)),
                pausado=pausado, en_ventana=pausado and nombre in self._pausados_por_foco,
            )
            if corriendo:
                en_marcha.append(f"▶ {nombre} {actual}")
            elif pausado:
                en_marcha.append(f"⏸ {nombre} {actual}")
        texto = f"{len(en_marcha)} activo" + ("" if len(en_marcha) == 1 else "s")
        if self.ins_activos.cget("text") != texto.upper():
            self.ins_activos.configure(text=texto.upper(), text_color=VERDE if en_marcha else TENUE)
        # El título se ve en la barra de tareas sin abrir la ventana.
        titulo = f"{', '.join(en_marcha)} — {TITULO}" if en_marcha else TITULO
        if self._grabando_desde is not None:
            titulo = "● REC — " + titulo
        if self.root.title() != titulo:
            self.root.title(titulo)
            if self.bandeja:
                self.bandeja.titulo(titulo)
        if reprogramar:
            self.root.after(500, self._refrescar_tiempos)

    def _ventana_activa(self):
        """¿Está el usuario en esta app (la ventana o uno de sus diálogos)?"""
        try:
            if os.name == "nt":
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(),
                                                              ctypes.byref(pid))
                return pid.value == os.getpid()
            return bool(str(self.root.tk.call("focus", "-displayof", self.root)))
        except Exception:
            return False

    def _pausa_por_ventana(self, ahora):
        """Mientras usas la app no corre el tiempo ni el autoshot; al volver al juego, siguen."""
        activa = self._ventana_activa()
        self.escucha.en_ventana = activa
        if activa:
            if not self.escucha.grabando_animacion:
                for nombre in list(self.registro.en_curso):
                    self.registro.pausar(nombre, ahora)
                    self._pausados_por_foco.add(nombre)
        elif self._pausados_por_foco:
            for nombre in self._pausados_por_foco:
                if self.registro.en_pausa(nombre):
                    self.registro.reanudar(nombre, ahora)
                    if nombre in self._ultima_foto:
                        self._ultima_foto[nombre] = ahora  # el rato en la app no cuenta como inactividad
            self._pausados_por_foco.clear()

    def _activo(self, nombre):
        """En marcha para el usuario (aunque esté en pausa solo porque usa la app)."""
        return self.registro.corriendo(nombre) or (nombre in self._pausados_por_foco
                                                   and self.registro.en_pausa(nombre))

    def _revisar_pausa_automatica(self, ahora):
        """Si pasan N segundos sin fotos, pausar contando solo hasta la última foto."""
        segundos = self.config.get("pausa_auto_seg", 30)
        # Con el autoshot encendido no: él toma fotos solo y la pausa lo detendría.
        if not segundos or self.escucha.grabando_animacion or self.config.get("autoshot"):
            return
        for nombre in list(self.registro.en_curso):
            ultima = self._ultima_foto.get(nombre)
            # Solo después de la primera foto de la sesión: un temporizador sin fotos
            # (por ejemplo «escribir») nunca se pausa solo.
            if ultima and (ahora - ultima).total_seconds() > segundos:
                self.registro.pausar(nombre, ultima)
                self.log(f"⏸ '{nombre}' en pausa: {texto_espera(segundos)} sin fotos. Se contó hasta la última foto; "
                         "la próxima foto lo reanuda.")

    def _captura(self, momento):
        """Se tomó (o empezó) una foto o animación."""
        for nombre in list(self.registro.pausados):
            self.registro.reanudar(nombre, momento)
            self.log(f"▶ '{nombre}' reanudado con la foto")
        for nombre in self.registro.en_curso:
            self._ultima_foto[nombre] = momento
        self._refrescar_tiempos(reprogramar=False)

    def accion_secundaria(self, nombre):
        if self.registro.en_pausa(nombre) and not self._activo(nombre):
            self.registro.parar(nombre)
            self._ultima_foto.pop(nombre, None)
            self.log(f"■ '{nombre}' terminado (estaba en pausa)")
            self._refrescar_tiempos(reprogramar=False)
        else:
            self.cancelar_timer(nombre)

    def _latido(self):
        self.registro.latido()
        self.root.after(LATIDO_CADA_MS, self._latido)

    # ------------------------------------------------------------------ miniaturas

    def _cargar_miniaturas(self, carpeta):
        """Hilo: lee las fotos y animaciones más recientes de la carpeta."""
        try:
            elementos = [p for p in carpeta.iterdir()
                         if p.suffix.lower() in EXTENSIONES_FOTO or p.suffix.lower() == ".avif"
                         or (p.is_dir() and animacion.PATRON_CARPETA.match(p.name))]
            elementos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            elementos = []
        lista = []
        for ruta in elementos:
            if len(lista) >= MAX_MINIATURAS:
                break
            try:
                if ruta.suffix.lower() == ".avif":
                    with Image.open(ruta) as img:
                        n = getattr(img, "n_frames", 1)
                        lista.append((ruta, marcar_animacion(hacer_miniatura(img.convert("RGB")), n), n))
                elif ruta.is_dir():
                    cuadros = sorted(p for p in ruta.iterdir() if p.suffix.lower() in EXTENSIONES_FOTO)
                    if not cuadros:
                        continue
                    with Image.open(cuadros[0]) as img:
                        img.draft("RGB", (TAM_MINIATURA[0] * 2, TAM_MINIATURA[1] * 2))
                        lista.append((ruta, marcar_animacion(hacer_miniatura(img), len(cuadros)), len(cuadros)))
                else:
                    with Image.open(ruta) as img:
                        img.draft("RGB", (TAM_MINIATURA[0] * 2, TAM_MINIATURA[1] * 2))  # acelera JPG
                        lista.append((ruta, hacer_miniatura(img), None))
            except Exception:
                continue
        self.eventos.put(("miniaturas", carpeta, lista, len(elementos)))

    def _dibujar_miniaturas(self):
        for w in self.grilla_fotos.winfo_children():
            w.destroy()
        for i, (ruta, img, cuadros) in enumerate(self.miniaturas):
            celda = ctk.CTkFrame(self.grilla_fotos, fg_color=TARJETA, corner_radius=8, border_width=1,
                                 border_color=BORDE)
            celda.grid(row=i // 2, column=i % 2, sticky="nsew", padx=5, pady=5)
            foto = ctk.CTkLabel(celda, text="", image=ctk.CTkImage(img, size=TAM_MINIATURA), cursor="hand2")
            foto.pack(padx=4, pady=(4, 0))
            if not cuadros:
                texto = etiqueta_foto(ruta)
            elif ruta.is_dir():
                texto = f"{ruta.name} · AVIF ✓" if (ruta / f"{ruta.name}.avif").exists() else ruta.name
            else:
                texto = ruta.stem
            etiqueta = ctk.CTkLabel(celda, text=texto[:24], font=fuente(10), text_color=TENUE,
                                    anchor="w", height=20)
            etiqueta.pack(fill="x", padx=8, pady=(0, 4))
            for w in (foto, etiqueta):
                if ruta.is_dir():
                    w.bind("<Button-1>", lambda e, r=ruta: DialogoRecorte(self, r))
                else:
                    w.bind("<Button-1>", lambda e, r=ruta: abrir(r))
        if not self.miniaturas:
            ctk.CTkLabel(self.grilla_fotos, text="Aquí aparecerán tus\nfotos y animaciones.", font=fuente(12),
                         text_color=TENUE).grid(row=0, column=0, columnspan=2, pady=40)
        self.ins_fotos.configure(text=str(max(getattr(self, "_total_fotos", 0), len(self.miniaturas))))

    # ------------------------------------------------------------------ eventos

    def _procesar_eventos(self):
        if self._evento_mostrar and ctypes.windll.kernel32.WaitForSingleObject(self._evento_mostrar, 0) == 0:
            self.mostrar_ventana()  # alguien abrió la app otra vez: mostrar esta
        try:
            while True:
                evento = self.eventos.get_nowait()
                tipo = evento[0]
                if tipo == "log":
                    self.log(evento[1])
                elif tipo == "mando":
                    if evento[1]:
                        self.pastilla_mando.configure(text="●  Mando conectado", text_color=VERDE,
                                                      fg_color=VERDE_FONDO)
                    else:
                        self.pastilla_mando.configure(text="●  Sin mando", text_color=TENUE, fg_color=TARJETA)
                elif tipo == "motor":
                    self.lbl_motor.configure(text=f"Captura: {evento[1]}  ·  Capturador")
                elif tipo == "error":
                    self.escucha_error = evento[1]
                    self.pastilla_mando.configure(text="●  Mando no disponible", text_color=ROJO,
                                                  fg_color=ROJO_FONDO)
                    self.log(f"[!] {evento[1]}")
                elif tipo == "autoshot":
                    self._mostrar_autoshot(evento[1])
                elif tipo == "destello":
                    if self.config.get("avisos_pantalla", True):
                        self.aviso.destello()
                elif tipo == "bandeja":
                    if evento[1] == "abrir":
                        self.mostrar_ventana()
                    else:
                        self.cerrar()
                elif tipo == "captura":
                    self._captura(evento[1])
                elif tipo == "timer_global":
                    self._timer_global(evento[1])
                elif tipo == "autoshot_alternar":
                    self._alternar_autoshot()
                elif tipo == "combo_cancelado":
                    self._cancelar_grabacion()
                elif tipo == "combo":
                    self._combo_grabado(evento[1])
                elif tipo == "miniaturas":
                    if evento[1] == self._carpeta_mostrada:  # pudo cambiar mientras cargaba
                        self.miniaturas = evento[2] + self.miniaturas
                        del self.miniaturas[MAX_MINIATURAS:]
                        self._total_fotos = evento[3]  # se muestran las más recientes, se cuentan todas
                        self._dibujar_miniaturas()
                elif tipo == "miniatura":
                    if self._en_carpeta_mostrada(evento[1]):
                        self.miniaturas.insert(0, (evento[1], evento[2], None))
                        self._total_fotos = getattr(self, "_total_fotos", 0) + 1
                        del self.miniaturas[MAX_MINIATURAS:]
                        self._dibujar_miniaturas()
                elif tipo == "avif_creado":
                    carpeta, destino, n, error = evento[1:]
                    if error:
                        self.log(f"[!] No se pudo crear el AVIF de {carpeta.name}: {error}")
                    else:
                        self.log(f"✓ {destino.name}: {n} cuadros, {destino.stat().st_size / 1e6:.2f} MB")
                        self._insertar_miniatura(destino, n)
                elif tipo.startswith("anim_"):
                    self._evento_animacion(tipo, evento[1:])
        except queue.Empty:
            pass
        self.root.after(50, self._procesar_eventos)

    # ------------------------------------------------------------------ grabar combo

    def _grabar_combo(self, titulo, al_terminar):
        if self.escucha_error:
            Dialogo.mostrar(self.root, "Mando no disponible", self.escucha_error)
            return
        self._al_grabar = al_terminar
        d = ctk.CTkToplevel(self.root, fg_color=PANEL)
        d.title(titulo)
        d.transient(self.root)
        d.resizable(False, False)
        poner_icono(d)
        arriba = ctk.CTkFrame(d, fg_color="transparent")
        arriba.pack(fill="x", padx=8, pady=(8, 0))
        boton(arriba, "✕", self._cancelar_grabacion, "fantasma", width=30, height=28,
              font=fuente(14, "bold")).pack(side="right")
        cuerpo = ctk.CTkFrame(d, fg_color="transparent")
        cuerpo.pack(padx=36, pady=(0, 26))
        ctk.CTkLabel(cuerpo, text="🎮", font=fuente(34)).pack()
        ctk.CTkLabel(cuerpo, text=titulo, font=fuente(16, "bold"), text_color=TEXTO).pack(pady=(6, 0))
        ctk.CTkLabel(cuerpo, text="Presiona el atajo en el mando: un botón\n"
                                  "(o mantén una combinación y suelta).",
                     font=fuente(13), text_color=TENUE, justify="center").pack(pady=(6, 4))
        ctk.CTkLabel(cuerpo, text="Esc para salir", font=fuente(12, "bold"), text_color=TENUE).pack()
        d.protocol("WM_DELETE_WINDOW", self._cancelar_grabacion)
        d.bind("<Escape>", lambda e: self._cancelar_grabacion())
        self._dialogo_grabar = d

        def centrar():
            d.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - d.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - d.winfo_height()) // 3
            d.geometry(f"+{max(x, 0)}+{max(y, 0)}")
            try:
                d.grab_set()
            except tk.TclError:
                pass
        d.after(30, centrar)
        self.escucha.grabar_combo()

    def _cancelar_grabacion(self):
        self.escucha.cancelar_grabacion()
        self._cerrar_dialogo()
        self._al_grabar = None

    def _cerrar_dialogo(self):
        if self._dialogo_grabar is not None:
            try:
                self._dialogo_grabar.grab_release()
            except tk.TclError:
                pass
            self._dialogo_grabar.destroy()
            self._dialogo_grabar = None

    def _combo_grabado(self, mascara):
        self._cerrar_dialogo()
        al_terminar, self._al_grabar = self._al_grabar, None
        if al_terminar is None:
            return
        nombres = cap.mascara_a_nombres(mascara)
        duenos = self.config["atajos"] + [
            {"nombre": "atajo de temporizador", "botones": self.config.get("atajo_timer")},
            {"nombre": "atajo de animación", "botones": self.config.get("atajo_anim")},
            {"nombre": "atajo de autoshot", "botones": self.config.get("atajo_autoshot")}]
        for dueno in duenos:
            if dueno.get("botones") and cap.nombres_a_mascara(dueno["botones"]) == mascara:
                Dialogo.mostrar(self.root, "Combinación ocupada",
                                f"{cap.texto_combo(nombres)} ya está asignado a «{dueno['nombre']}».")
                return
        al_terminar(nombres)

    def _quitar_teclas(self):
        """Por ahora los atajos son solo del mando: quitar las teclas guardadas antes."""
        cambios = []
        for a in list(self.config["atajos"]):
            if any(cap.es_tecla(b) for b in a["botones"]):
                a["botones"] = [b for b in a["botones"] if not cap.es_tecla(b)]
                if not a["botones"]:
                    self.config["atajos"].remove(a)
                cambios.append(a["nombre"])
        for clave, texto in (("atajo_timer", "atajo de temporizador"), ("atajo_anim", "atajo de animación")):
            botones = self.config.get(clave) or []
            if any(cap.es_tecla(b) for b in botones):
                resto = [b for b in botones if not cap.es_tecla(b)]
                if resto:
                    self.config[clave] = resto
                else:
                    self.config.pop(clave, None)
                cambios.append(texto)
        return cambios

    def _pedir_nombre(self, titulo, mensaje, sugerido):
        nombre = Dialogo.mostrar(self.root, titulo, mensaje,
                                 (("Cancelar", None, "normal"), ("Continuar", True, "verde")), entrada=sugerido)
        if not nombre:
            return None
        usados = {a["nombre"] for a in self.config["atajos"]} | {t["nombre"] for t in self.config["timers"]}
        if nombre in usados:
            Dialogo.mostrar(self.root, "Nombre repetido", f"Ya existe algo llamado «{nombre}».")
            return None
        return nombre

    # ------------------------------------------------------------------ fotos

    def agregar_foto(self):
        usados = {a["nombre"] for a in self.config["atajos"]}
        n = 1
        while f"Atajo {n}" in usados:
            n += 1
        nombre = f"Atajo {n}"

        def listo(botones):
            self.config["atajos"].append({"nombre": nombre, "botones": botones})
            self._guardar()
            self.escucha.recargar()
            self._refrescar_fotos()
            self.log(f"Atajo de foto '{nombre}' = {cap.texto_combo(botones)}")
        self._grabar_combo("Nuevo atajo de foto", listo)

    def borrar_foto(self, nombre):
        self.config["atajos"] = [a for a in self.config["atajos"] if a["nombre"] != nombre]
        self._guardar()
        self.escucha.recargar()
        self._refrescar_fotos()
        self.log(f"Atajo de foto '{nombre}' borrado")

    def cambiar_carpeta(self):
        """Panel derecho: cambia la carpeta general."""
        nueva = filedialog.askdirectory(initialdir=self.config["carpeta"], title="Carpeta general para las fotos")
        if nueva:
            self.config["carpeta"] = os.path.normpath(nueva)
            self._guardar()
            self._mostrar_carpeta()
            self.log(f"Carpeta general: {self.config['carpeta']}")

    def elegir_carpeta(self):
        """Botón 📁: carpeta del temporizador seleccionado, o la general si no hay ninguno."""
        timer = self._timer(self.config.get("timer_seleccionado"))
        titulo = f"Carpeta para las fotos de «{timer['nombre']}»" if timer else "Carpeta general para las fotos"
        nueva = filedialog.askdirectory(initialdir=str(cap.carpeta_actual(self.config)), title=titulo)
        if not nueva:
            return
        nueva = os.path.normpath(nueva)
        if timer:
            timer["carpeta"] = nueva
            self.log(f"Las fotos de «{timer['nombre']}» se guardarán en {nueva}")
        else:
            self.config["carpeta"] = nueva
            self.log(f"Carpeta general: {nueva}")
        self._guardar()
        self._mostrar_carpeta()

    def usar_carpeta_general(self):
        timer = self._timer(self.config.get("timer_seleccionado"))
        if timer and timer.pop("carpeta", None):
            self._guardar()
            self._mostrar_carpeta()
            self.log(f"«{timer['nombre']}» vuelve a usar la carpeta general.")

    def abrir_fotos(self):
        carpeta = cap.carpeta_actual(self.config)
        carpeta.mkdir(parents=True, exist_ok=True)
        abrir(carpeta)

    # ------------------------------------------------------------------ timers

    def nuevo_timer(self):
        nombre = self._pedir_nombre("Nuevo temporizador", "Nombre de la actividad (por ejemplo: escribir, fotos).", "")
        if not nombre:
            return
        self.config["timers"].append({"nombre": nombre})
        self._guardar()
        self.seleccionar_timer(nombre)
        self._refrescar_timers()

    def borrar_timer(self, nombre):
        if not Dialogo.confirmar(self.root, "Borrar temporizador",
                                 f"¿Borrar «{nombre}»?\n\nEl historial ya guardado se conserva.",
                                 si="Borrar", estilo="rojo"):
            return
        if self.registro.corriendo(nombre):
            self._alternar_timer(nombre, datetime.now())
        self.config["timers"] = [t for t in self.config["timers"] if t["nombre"] != nombre]
        self._guardar()
        self.escucha.recargar()
        self._refrescar_timers()

    def alternar_timer(self, nombre):
        self.seleccionar_timer(nombre)
        self._alternar_timer(nombre, datetime.now())

    def seleccionar_timer(self, nombre, alternar=False):
        """alternar=True (clic en la tarjeta): si ya estaba seleccionado, lo deselecciona."""
        if self.config["timer_seleccionado"] == nombre:
            if not alternar:
                return
            nombre = None
        self.config["timer_seleccionado"] = nombre
        self._guardar()
        self._refrescar_tiempos(reprogramar=False)
        self._mostrar_carpeta()

    def _timer_global(self, momento):
        """Atajo global: para el seleccionado si corre; si no, para los demás e inicia el seleccionado."""
        nombre = self.config["timer_seleccionado"]
        if nombre is None or self._timer(nombre) is None:
            self.log("[!] Selecciona un temporizador para usar el atajo global.")
            return
        if not self._activo(nombre):
            for otro in list(self.registro.en_curso):
                self._alternar_timer(otro, momento)
            for otro in list(self.registro.pausados):
                if otro != nombre:
                    self.registro.parar(otro)
                    self._ultima_foto.pop(otro, None)
        self._alternar_timer(nombre, momento, desde_mando=True)

    def recortar_carpeta(self):
        """Abrir el editor de recorte con cualquier carpeta de cuadros (por ejemplo, una grabación vieja)."""
        inicial = str(cap.carpeta_actual(self.config))
        carpeta = filedialog.askdirectory(initialdir=inicial, title="Carpeta con los cuadros de la animación")
        if not carpeta:
            return
        try:
            hay = bool(animacion.cuadros_de(carpeta))
        except OSError as e:
            Dialogo.mostrar(self.root, "Recortar", f"No se pudo abrir la carpeta:\n{e}")
            return
        if not hay:
            Dialogo.mostrar(self.root, "Recortar", "Esa carpeta no tiene cuadros (PNG, JPG o WEBP).")
            return
        DialogoRecorte(self, carpeta)

    def destino_siguiente_foto(self, carpeta, extension):
        """Ruta con el siguiente número para algo sacado de una carpeta de cuadros.

        Si la carpeta es una animación grabada aquí (doric-anim_003), va junto a ella con su
        sufijo; si es una carpeta cualquiera, va a la carpeta de guardado actual."""
        carpeta = Path(carpeta)
        if "-anim_" in carpeta.name:
            base, sufijo = carpeta.parent, carpeta.name.rsplit("-anim_", 1)[0]
        else:
            base, sufijo = Path(cap.carpeta_actual(self.config)), cap.limpiar_sufijo(self.config.get("sufijo"))
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{sufijo}-{cap.reservar_numero(base, sufijo):03d}{extension}"

    def _insertar_miniatura(self, ruta, cuadros=None):
        """Pone una foto o AVIF recién creado al principio de la lista de la izquierda."""
        if not self._en_carpeta_mostrada(ruta):
            return
        try:
            with Image.open(ruta) as img:
                mini = hacer_miniatura(img.convert("RGB"))
            if cuadros:
                mini = marcar_animacion(mini, cuadros)
            self.miniaturas.insert(0, (Path(ruta), mini, cuadros))
            self._total_fotos = getattr(self, "_total_fotos", 0) + 1
            del self.miniaturas[MAX_MINIATURAS:]
            self._dibujar_miniaturas()
        except Exception:
            pass

    def guardar_cuadro_como_foto(self, carpeta, cuadro):
        """Copia un cuadro de la animación como foto suelta, con el siguiente número."""
        carpeta, cuadro = Path(carpeta), Path(cuadro)
        destino = self.destino_siguiente_foto(carpeta, cuadro.suffix)
        try:
            shutil.copy2(cuadro, destino)  # copia exacta: sin volver a comprimir
        except OSError as e:
            self.log(f"[!] No se pudo guardar el cuadro: {e}")
            return
        self.log(f"[foto] {destino.name} ← cuadro {cuadro.stem.rsplit('-', 1)[-1]} de {carpeta.name}")
        self._insertar_miniatura(destino)

    def crear_avif(self, carpeta, rutas, destino, fps):
        modo = self.config["prioridad"]
        self.log(f"Creando el AVIF de {carpeta.name} con {len(rutas)} cuadros…")

        def trabajo():
            try:
                if not animacion.avif_disponible():
                    raise RuntimeError("este Pillow no tiene AVIF (ejecuta instalar.bat)")
                rutas_txt = [str(r) for r in rutas]
                if self.escucha.pool is not None:
                    self.escucha.pool.submit(trabajador.crear_avif, rutas_txt, str(destino), fps,
                                             animacion.HILOS.get(modo), modo).result()
                else:
                    animacion.crear_avif(rutas, destino, fps, hilos=animacion.HILOS.get(modo))
                self.eventos.put(("avif_creado", carpeta, destino, len(rutas), None))
            except Exception as e:
                self.eventos.put(("avif_creado", carpeta, destino, len(rutas), str(e)))
        threading.Thread(target=trabajo, daemon=True).start()

    def cancelar_timer(self, nombre):
        if not self._activo(nombre):
            return
        actual = formato_duracion(self.registro.sesion(nombre))
        if not Dialogo.confirmar(
                self.root, "Cancelar sesión",
                f"Se descartarán {actual} de la sesión actual de «{nombre}», como si nunca hubiera "
                "pasado. Las sesiones anteriores no se tocan.", si="Descartar", estilo="rojo"):
            return
        descartado = self.registro.cancelar(nombre)
        self._pausados_por_foco.discard(nombre)
        self._ultima_foto.pop(nombre, None)
        if descartado is not None:
            self.log(f"✕ '{nombre}': sesión cancelada ({formato_duracion(descartado.total_seconds())} descartados)")
        self._refrescar_tiempos(reprogramar=False)

    # ------------------------------------------------------------------ atajo global

    def _refrescar_global(self):
        """Dibuja las filas del atajo de temporizador, del de animación y del de autoshot."""
        for fila, clave, asignar, quitar in ((self.fila_global, "atajo_timer", self.asignar_global, self.quitar_global),
                                             (self.fila_anim, "atajo_anim", self.asignar_anim, self.quitar_anim),
                                             (self.fila_autoshot, "atajo_autoshot", self.asignar_autoshot,
                                              self.quitar_autoshot)):
            for w in fila.winfo_children():
                w.destroy()
            atajo = self.config.get(clave)
            if atajo:
                insignia(fila, cap.texto_combo(atajo), color=VERDE, borde=VERDE_BORDE).pack(
                    side="left", padx=14, pady=12)
                boton(fila, "Quitar", quitar, "fantasma", width=10, height=28,
                      font=fuente(12)).pack(side="right", padx=8)
            else:
                ctk.CTkLabel(fila, text="Sin asignar", font=fuente(13), text_color=TENUE).pack(
                    side="left", padx=14, pady=10)
                boton(fila, "Asignar", asignar, "verde", width=90, height=30).pack(
                    side="right", padx=8, pady=8)

    def asignar_autoshot(self):
        def listo(botones):
            self.config["atajo_autoshot"] = botones
            self._guardar()
            self.escucha.recargar()
            self._refrescar_global()
            self.log(f"Atajo de autoshot = {cap.texto_combo(botones)}")
        self._grabar_combo("Atajo de autoshot", listo)

    def quitar_autoshot(self):
        self.config.pop("atajo_autoshot", None)
        self._guardar()
        self.escucha.recargar()
        self._refrescar_global()

    def _alternar_autoshot(self):
        """Desde el mando: prende o apaga el autoshot, con sonido para saberlo sin ver la pantalla."""
        self.var_autoshot.set(not self.config.get("autoshot"))
        self._cambiar_autoshot()
        pitido(self.config["autoshot"])

    def asignar_anim(self):
        def listo(botones):
            self.config["atajo_anim"] = botones
            self._guardar()
            self.escucha.recargar()
            self._refrescar_global()
            self.log(f"Atajo de animación = {cap.texto_combo(botones)}")
        self._grabar_combo("Atajo de animación", listo)

    def quitar_anim(self):
        self.escucha.detener_animacion()
        self.config.pop("atajo_anim", None)
        self._guardar()
        self.escucha.recargar()
        self._refrescar_global()

    def asignar_global(self):
        def listo(botones):
            self.config["atajo_timer"] = botones
            self._guardar()
            self.escucha.recargar()
            self._refrescar_global()
            self._refrescar_tiempos(reprogramar=False)
            self.log(f"Atajo de temporizador = {cap.texto_combo(botones)}")
        self._grabar_combo("Atajo global de temporizador", listo)

    def quitar_global(self):
        self.config.pop("atajo_timer", None)
        self._guardar()
        self.escucha.recargar()
        self._refrescar_global()
        self._refrescar_tiempos(reprogramar=False)

    def _alternar_timer(self, nombre, momento, desde_mando=False):
        if self._timer(nombre) is None:
            return
        if self._activo(nombre) and not self.registro.corriendo(nombre):
            self.registro.reanudar(nombre, momento)  # solo pausado por usar la app: se detiene como uno en marcha
        self._pausados_por_foco.discard(nombre)
        era_pausa = self.registro.en_pausa(nombre)
        sesion = self.registro.sesion(nombre, momento)
        corriendo, duracion = self.registro.alternar(nombre, momento)
        if corriendo and era_pausa:
            self._ultima_foto[nombre] = momento  # reanudar cuenta como actividad (si no, se pausaría al instante)
        else:
            self._ultima_foto.pop(nombre, None)
        if corriendo:
            self.log(f"▶ '{nombre}' {'reanudado' if era_pausa else 'iniciado'}")
        else:
            self.log(f"■ '{nombre}' detenido: {formato_duracion(sesion)}")
        if desde_mando and self.config["pitido_timers"]:
            pitido(corriendo)
        self._refrescar_tiempos(reprogramar=False)

    def abrir_historial(self):
        if not self.registro.archivo.exists():
            Dialogo.mostrar(self.root, "Historial", "Todavía no hay sesiones guardadas.")
            return
        abrir(self.registro.archivo)

    # ------------------------------------------------------------------ cerrar

    def cerrar(self):
        self.registro.parar_todos()
        self.escucha.detener_animacion()
        if self.escucha.ocupado():
            # No perder fotogramas que aún están en memoria: esperar a que se guarden.
            self.log("Terminando de guardar antes de cerrar…")
            self.root.protocol("WM_DELETE_WINDOW", lambda: None)
            self.root.after(300, self.cerrar)
            return
        self.escucha.detener()
        self.escucha.join(timeout=3)
        if self.bandeja:
            self.bandeja.cerrar()
        self.aviso.ocultar()
        self.root.destroy()

    # ------------------------------------------------------------------ sufijo y animaciones

    @staticmethod
    def _resumen_medidas(m):
        partes = [f"{m['duracion_animacion_s']} s de animación para {m['duracion_real_s']} s reales"]
        if m.get("fps_del_juego"):
            partes.append(f"juego ≈ {m['fps_del_juego']:.0f} fps")
        if m.get("monitor_hz"):
            partes.append(f"monitor {m['monitor_hz']} Hz")
        partes.append(f"{m['repetidos']} repetidos")
        if m.get("repetidos_por_memoria"):
            partes.append(f"{m['repetidos_por_memoria']} por no alcanzar a guardar")
        if m.get("descartados_por_llegar_antes"):
            partes.append(f"{m['descartados_por_llegar_antes']} descartados")
        if m.get("captura_ms_mediana") is not None:
            partes.append(f"captura {m['captura_ms_mediana']} ms (p95 {m['captura_ms_p95']})")
        return "   ↳ " + " · ".join(partes)

    def _actualizar_indicador(self):
        """Circulito: rojo grabando, gris con temporizador corriendo, oculto si no."""
        if not self.config.get("avisos_pantalla", True):
            base = "oculto"
        elif self._grabando_desde is not None:
            base = "rec"
        elif self.registro.en_curso:
            base = "listo"
        else:
            base = "oculto"
        self.aviso.estado(base)

    def _sufijo_cambiado(self):
        sufijo = cap.limpiar_sufijo(self.var_sufijo.get())
        ext = cap.extension(self.config.get("formato"))
        self.lbl_ejemplo.configure(text=f"{sufijo}-001.{ext}  ·  {sufijo}-anim_002")
        if self.config.get("sufijo") != sufijo:
            self.config["sufijo"] = sufijo
            # Guardar el archivo sin escribirlo con cada tecla.
            if getattr(self, "_guardar_sufijo", None):
                self.root.after_cancel(self._guardar_sufijo)
            self._guardar_sufijo = self.root.after(600, self._guardar)

    def _evento_animacion(self, tipo, datos):
        if tipo == "anim_inicio":
            self._grabando_desde = time.monotonic()
            self.pastilla_rec.configure(text="●  REC 0:00")
            self.pastilla_rec.pack(side="left", padx=(0, 10), before=self.pastilla_mando)
            self.log(f"● Grabando animación en {datos[0].name}…")
            self._actualizar_indicador()
            if self.config["sonido_anim"]:
                sonido_anim(True)
        elif tipo == "anim_progreso":
            cuadros, segundos = datos
            self.pastilla_rec.configure(text=f"●  REC {int(segundos) // 60}:{int(segundos) % 60:02d} · {cuadros}")
        elif tipo == "anim_fin":
            carpeta, miniatura, total, motivo, medidas = datos
            self._grabando_desde = None
            self.pastilla_rec.pack_forget()
            self._actualizar_indicador()
            if self.config["sonido_anim"]:
                sonido_anim(False)
            if motivo.startswith("error"):
                self.log(f"[!] Animación {carpeta.name}: {motivo}")
            else:
                self.log(f"■ {carpeta.name}: {total} cuadros grabados. Guardando…")
                self.log(self._resumen_medidas(medidas))
            if miniatura is not None and total and self._en_carpeta_mostrada(carpeta):
                img = marcar_animacion(hacer_miniatura(miniatura), total)
                self.miniaturas.insert(0, (carpeta, img, total))
                self._total_fotos = getattr(self, "_total_fotos", 0) + 1
                del self.miniaturas[MAX_MINIATURAS:]
                self._dibujar_miniaturas()
        elif tipo == "anim_guardando":
            carpeta, hechos, total = datos
            self.lbl_estado.configure(text=f"Capturador  ·  Guardando {carpeta.name}: {hechos}/{total} cuadros")
        elif tipo == "anim_avif":
            self.lbl_estado.configure(text=f"Capturador  ·  Creando el AVIF animado de {datos[0].name}…")
        elif tipo == "anim_guardada":
            carpeta, final, total, segundos, error = datos
            # La miniatura apuntaba a la carpeta; ahora al resultado final (p. ej. el .avif).
            self.miniaturas = [(final if r == carpeta else r, img, n) for r, img, n in self.miniaturas]
            self._dibujar_miniaturas()
            if error:
                self.log(f"[!] {carpeta.name}: {error}")
            if total and final.is_file():
                self.log(f"✓ {final.name}: {total} cuadros ({segundos:.1f} s), {final.stat().st_size / 1e6:.2f} MB")
            elif total and not error:
                self.log(f"✓ {carpeta.name} guardada: {total} cuadros ({segundos:.1f} s)")


# --------------------------------------------------------------------------
# Inicio
# --------------------------------------------------------------------------

_mutex = None


NOMBRE_EVENTO_MOSTRAR = "CapturadorSilksong_Mostrar"


def crear_evento_mostrar():
    """Evento de Windows con el que una segunda copia le pide a esta que se muestre."""
    if os.name != "nt":
        return None
    return ctypes.windll.kernel32.CreateEventW(None, False, False, NOMBRE_EVENTO_MOSTRAR)


def ya_esta_abierta():
    """Evita dos copias abiertas (tomarían cada foto dos veces)."""
    global _mutex
    if os.name != "nt":
        return False
    k32 = ctypes.windll.kernel32
    _mutex = k32.CreateMutexW(None, False, "CapturadorSilksong_UnaInstancia")
    return k32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def main():
    if os.name == "nt":
        try:
            # Que la barra de tareas muestre nuestro icono y no el de Python.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(cap.APP_ID)
        except Exception:
            pass
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    if ya_esta_abierta():
        # Ya hay una copia (quizá escondida en la bandeja): pedirle que se muestre y salir.
        evento = crear_evento_mostrar()
        if evento:
            ctypes.windll.kernel32.SetEvent(evento)
        root.destroy()
        return

    def al_fallar(tipo, valor, tb):
        registrar_error("".join(traceback.format_exception(tipo, valor, tb)))
        messagebox.showerror(TITULO, f"Ocurrió un error:\n{valor}\n\nDetalles en {LOG_ERRORES.name}")
    root.report_callback_exception = al_fallar

    try:
        app = App(root)
        if bandeja.ARG_BANDEJA in sys.argv:  # abierta al iniciar Windows: quedarse en la bandeja
            if app.bandeja and app.bandeja.disponible:
                root.withdraw()
            else:
                root.iconify()
    except Exception as e:
        registrar_error(traceback.format_exc())
        messagebox.showerror(TITULO, f"No se pudo iniciar:\n{e}\n\nDetalles en {LOG_ERRORES.name}")
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
