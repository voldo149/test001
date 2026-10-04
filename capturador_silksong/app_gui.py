"""
Ventana de Capturador Silksong: fotos y temporizadores con el mando.

Estilo oscuro inspirado en el editor de guías de Speedrunz. La ventana nunca
se pone al frente sola ni toma el foco, así que se puede dejar abierta
(o minimizada) mientras juegas o escribes.
"""

import ctypes
import os
import queue
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

import capturador as cap
from tiempos import RegistroTiempos, formato_duracion

CARPETA = cap.CARPETA_SCRIPT
ICONO = CARPETA / "icono.ico"
LOG_ERRORES = CARPETA / "errores.log"
TITULO = "Capturador Silksong"
LATIDO_CADA_MS = 30_000
MAX_MINIATURAS = 24
TAM_MINIATURA = (132, 74)
EXTENSIONES_FOTO = {".png", ".jpg", ".jpeg"}

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
VERDE = "#2fe0a0"
VERDE_FONDO = "#0f3d30"
VERDE_HOVER = "#145040"
VERDE_BORDE = "#1d6b52"
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


def ruta_corta(ruta, maximo=40):
    return ruta if len(ruta) <= maximo else "…" + ruta[-(maximo - 1):]


def abrir(ruta):
    if hasattr(os, "startfile"):
        os.startfile(ruta)


def pitido(inicio):
    """Pitido corto (no es un sonido de error de Windows): agudo = inicia, grave = para."""
    if os.name != "nt":
        return
    import winsound

    def _sonar():
        if inicio:
            winsound.Beep(1200, 90)
        else:
            winsound.Beep(700, 90)
            winsound.Beep(500, 120)
    threading.Thread(target=_sonar, daemon=True).start()


def etiqueta_foto(ruta):
    """silksong_2026-10-04_21-10-05_123_foto1 -> '04/10 21:10 · foto1'."""
    partes = ruta.stem.split("_")
    try:
        fecha = datetime.strptime(f"{partes[1]}_{partes[2]}", "%Y-%m-%d_%H-%M-%S")
        resto = "_".join(partes[4:])
        return f"{fecha:%d/%m %H:%M}" + (f" · {resto}" if resto else "")
    except (IndexError, ValueError):
        return ruta.stem


def hacer_miniatura(img):
    """Reduce rápido (reduce() es mucho más barato que redimensionar directo)."""
    factor = max(1, min(img.width // (TAM_MINIATURA[0] * 2), img.height // (TAM_MINIATURA[1] * 2)))
    peque = img.reduce(factor) if factor > 1 else img.copy()
    peque.thumbnail((TAM_MINIATURA[0] * 2, TAM_MINIATURA[1] * 2))
    return peque.convert("RGB")


def poner_icono(ventana):
    # CustomTkinter pone su propio icono ~200 ms después de crear la ventana.
    if ICONO.exists() and os.name == "nt":
        ventana.after(250, lambda: ventana.iconbitmap(str(ICONO)))


# --------------------------------------------------------------------------
# Piezas visuales reutilizables
# --------------------------------------------------------------------------

def boton(padre, texto, comando, estilo="normal", **kw):
    estilos = {
        "verde": dict(fg_color=VERDE_FONDO, hover_color=VERDE_HOVER, text_color="#d6fbec",
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

        boton_txt = cap.texto_combo(timer["botones"]) if timer.get("botones") else "Sin botón"
        ctk.CTkLabel(self, text=f"🎮  {boton_txt}", font=fuente(12), text_color=TENUE,
                     anchor="w").pack(fill="x", padx=16, pady=(2, 0))

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
        if timer.get("botones"):
            boton(abajo, "Quitar botón", lambda: app.quitar_boton_timer(self.nombre), "fantasma",
                  **chico).pack(side="right")
        else:
            boton(abajo, "+ Botón", lambda: app.asignar_boton_timer(self.nombre), "fantasma",
                  **chico).pack(side="right")

    def _poner(self, clave, widget, **kw):
        # Solo reconfigurar si cambió: redibujar es lo caro en CustomTkinter.
        if self._cache.get(clave) != kw:
            self._cache[clave] = kw
            widget.configure(**kw)

    def actualizar(self, corriendo, actual, hoy, semana, total):
        self._poner("reloj", self.reloj, text=actual, text_color=VERDE if corriendo else TENUE)
        self._poner("borde", self, border_color=VERDE_BORDE if corriendo else BORDE)
        self._poner("estado", self.estado, text="● EN MARCHA" if corriendo else "DETENIDO",
                    text_color=VERDE if corriendo else TENUE)
        if corriendo:
            self._poner("btn", self.btn, text="■  Parar", fg_color=ROJO_FONDO, hover_color=ROJO_HOVER,
                        text_color=ROJO, border_color="#5c2433")
        else:
            self._poner("btn", self.btn, text="▶  Iniciar", fg_color=VERDE_FONDO, hover_color=VERDE_HOVER,
                        text_color="#d6fbec", border_color=VERDE_BORDE)
        for clave, valor in (("hoy", hoy), ("semana", semana), ("total", total)):
            self._poner(clave, self.totales[clave], text=valor)


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

    def _construir_detector(self):
        atajos, acciones = [], {}
        for a in self.config["atajos"]:
            clave = f"foto:{a['nombre']}"
            atajos.append({"nombre": clave, "botones": a["botones"]})
            acciones[clave] = ("foto", a["nombre"])
        for t in self.config["timers"]:
            if t.get("botones"):
                clave = f"timer:{t['nombre']}"
                atajos.append({"nombre": clave, "botones": t["botones"]})
                acciones[clave] = ("timer", t["nombre"])
        self.acciones = acciones
        self.detector = cap.DetectorAtajos(atajos, self.config["espera_entre_fotos"])

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

        capturador = None
        try:
            capturador = cap.Capturador(self.config["motor"], self.config["monitor"])
            self._avisar("motor", capturador.nombre_motor)
        except Exception as e:
            self._avisar("error", f"No se pudo preparar la captura de pantalla: {e}")

        guardador = cap.Guardador(self.config, aviso=lambda t: self._avisar("log", t.strip()),
                                  al_guardar=self._guardada)
        guardador.start()

        conectado = None
        ultimo_estado = 0.0
        estado_grabar = None  # None -> "soltar" -> "acumular"
        acumulado = 0

        while not self._detener.is_set():
            ahora = time.monotonic()
            m = xi.leer(ahora)

            if ahora - ultimo_estado > 1.0:
                ultimo_estado = ahora
                if xi.alguno_conectado() != conectado:
                    conectado = xi.alguno_conectado()
                    self._avisar("mando", conectado)

            if self._grabar:
                # Espera a que se suelte todo, junta lo que se presione y confirma al soltar.
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
                        if capturador is None:
                            self._avisar("log", "[!] La captura de pantalla no está disponible.")
                        else:
                            try:
                                guardador.cola.put((real, datetime.now(), capturador.tomar()))
                            except Exception as e:
                                self._avisar("log", f"[!] No se pudo tomar la foto: {e}")
                    else:
                        self._avisar("timer", real, datetime.now())

            time.sleep(cap.INTERVALO_LECTURA)

        guardador.cola.join()


# --------------------------------------------------------------------------
# Ventana
# --------------------------------------------------------------------------

class App:
    def __init__(self, root):
        self.root = root
        self.config = cap.cargar_config()
        self.config.setdefault("pitido_timers", False)
        self.registro = RegistroTiempos(CARPETA)
        self.eventos = queue.Queue()
        self.escucha = Escucha(self.config, self.eventos)
        self.escucha_error = None
        self._al_grabar = None
        self._dialogo_grabar = None
        self.tarjetas = {}
        self.miniaturas = []  # [(ruta, PIL.Image)] más reciente primero

        root.title(TITULO)
        root.geometry("1280x780")
        root.minsize(1100, 640)
        root.configure(fg_color=FONDO)
        poner_icono(root)

        self._construir_ui()
        self._refrescar_fotos()
        self._refrescar_timers()

        for actividad, duracion in self.registro.recuperadas:
            self.log(f"Recuperado '{actividad}' de un cierre inesperado: "
                     f"{formato_duracion(duracion.total_seconds())}")

        self.escucha.start()
        threading.Thread(target=self._cargar_miniaturas, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self.cerrar)
        root.after(100, self._procesar_eventos)
        root.after(500, self._refrescar_tiempos)
        root.after(LATIDO_CADA_MS, self._latido)

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
        ctk.CTkLabel(titulos, text="Silksong tools", font=fuente(11), text_color=TENUE,
                     height=14).pack(anchor="w")

        ctk.CTkFrame(enc, width=1, height=30, fg_color=BORDE).grid(row=0, column=1, padx=16)
        ctk.CTkLabel(enc, text="Apps / Capturador", font=fuente(12), text_color=TENUE).grid(row=0, column=2)

        derecha = ctk.CTkFrame(enc, fg_color="transparent")
        derecha.grid(row=0, column=4, padx=20)
        self.pastilla_mando = ctk.CTkLabel(derecha, text="●  Buscando mando…", font=fuente(12, "bold"),
                                           text_color=TENUE, fg_color=TARJETA, corner_radius=14,
                                           height=30, padx=12)
        self.pastilla_mando.pack(side="left", padx=(0, 14))
        boton(derecha, "Abrir fotos", self.abrir_fotos, "verde", width=120).pack(side="left", padx=(0, 8))
        boton(derecha, "Historial", self.abrir_historial, "azul", width=110).pack(side="left")

        separador(r).grid(row=0, column=0, columnspan=3, sticky="sew")

        # ---- Barra izquierda: fotos recientes
        izq = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0, width=290)
        izq.grid(row=1, column=0, sticky="ns")
        izq.grid_propagate(False)
        izq.grid_rowconfigure(1, weight=1)
        izq.grid_columnconfigure(0, weight=1)

        barra = ctk.CTkFrame(izq, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        boton(barra, "📁", self.abrir_fotos, "normal", width=38).pack(side="left")
        self.lbl_carpeta_nombre = ctk.CTkLabel(barra, text="", font=fuente(13, "bold"), text_color=TEXTO,
                                               fg_color=TARJETA, corner_radius=8, height=34, anchor="w",
                                               padx=12)
        self.lbl_carpeta_nombre.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.ins_fotos = insignia(barra, "0")
        self.ins_fotos.pack(side="left")

        self.grilla_fotos = ctk.CTkScrollableFrame(izq, fg_color="transparent", scrollbar_button_color=BORDE,
                                                   scrollbar_button_hover_color=TENUE)
        self.grilla_fotos.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        self.grilla_fotos.grid_columnconfigure((0, 1), weight=1, uniform="foto")

        ctk.CTkFrame(r, width=1, fg_color=BORDE, corner_radius=0).grid(row=1, column=0, sticky="nse")

        # ---- Centro: temporizadores
        centro = ctk.CTkFrame(r, fg_color=FONDO, corner_radius=0)
        centro.grid(row=1, column=1, sticky="nsew")
        centro.grid_columnconfigure(0, weight=1)
        centro.grid_rowconfigure(2, weight=1)

        cab, self.ins_activos = titulo_seccion(centro, "Temporizadores", "0 activos")
        cab.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 2))
        ctk.CTkLabel(centro, text="Inicia y para cada actividad con su botón del mando o aquí con un clic.",
                     font=fuente(12), text_color=TENUE, anchor="w").grid(row=1, column=0, sticky="ew", padx=28)

        self.grilla_timers = ctk.CTkScrollableFrame(centro, fg_color="transparent",
                                                    scrollbar_button_color=BORDE,
                                                    scrollbar_button_hover_color=TENUE)
        self.grilla_timers.grid(row=2, column=0, sticky="nsew", padx=18, pady=(12, 0))
        self.grilla_timers.grid_columnconfigure((0, 1), weight=1, uniform="timer")

        boton(centro, "+  Temporizador", self.nuevo_timer, "normal", anchor="w",
              font=fuente(13)).grid(row=3, column=0, sticky="ew", padx=28, pady=(8, 18))

        ctk.CTkFrame(r, width=1, fg_color=BORDE, corner_radius=0).grid(row=1, column=2, sticky="nsw")

        # ---- Panel derecho: atajos y ajustes
        der = ctk.CTkScrollableFrame(r, fg_color=PANEL, corner_radius=0, width=310,
                                     scrollbar_button_color=BORDE, scrollbar_button_hover_color=TENUE)
        der.grid(row=1, column=2, sticky="ns")
        pad = dict(padx=20, sticky="ew")
        der.grid_columnconfigure(0, weight=1)

        cab, self.ins_atajos = titulo_seccion(der, "Atajos de foto", "0")
        cab.grid(row=0, column=0, pady=(18, 10), **pad)
        self.lista_atajos = ctk.CTkFrame(der, fg_color="transparent")
        self.lista_atajos.grid(row=1, column=0, **pad)
        self.lista_atajos.grid_columnconfigure(0, weight=1)
        boton(der, "+  Atajo de foto", self.agregar_foto, "normal", anchor="w",
              font=fuente(13)).grid(row=2, column=0, pady=(8, 0), **pad)

        separador(der).grid(row=3, column=0, pady=20, **pad)

        cab, _ = titulo_seccion(der, "Formato", "Fotos")
        cab.grid(row=4, column=0, pady=(0, 10), **pad)
        self.seg_formato = ctk.CTkSegmentedButton(
            der, values=["PNG", "JPG"], command=self._cambiar_formato, height=36, corner_radius=8,
            font=fuente(13), fg_color=TARJETA, selected_color=SELECCION, selected_hover_color=SELECCION,
            unselected_color=TARJETA, unselected_hover_color=TARJETA_HOVER, text_color=TEXTO)
        self.seg_formato.set("JPG" if self.config["formato"].lower() in ("jpg", "jpeg") else "PNG")
        self.seg_formato.grid(row=5, column=0, **pad)

        ctk.CTkLabel(der, text="Carpeta", font=fuente(12), text_color=TENUE, anchor="w").grid(
            row=6, column=0, pady=(16, 4), **pad)
        fila = ctk.CTkFrame(der, fg_color="transparent")
        fila.grid(row=7, column=0, **pad)
        self.lbl_carpeta = ctk.CTkLabel(fila, text="", font=fuente(12), text_color=TEXTO, fg_color=TARJETA,
                                        corner_radius=8, height=36, anchor="w", padx=12)
        boton(fila, "Cambiar", self.cambiar_carpeta, "normal", width=84, height=36).pack(side="right", padx=(8, 0))
        self.lbl_carpeta.pack(side="left", fill="x", expand=True)
        self._mostrar_carpeta()

        separador(der).grid(row=8, column=0, pady=20, **pad)

        cab, _ = titulo_seccion(der, "Sonidos")
        cab.grid(row=9, column=0, pady=(0, 6), **pad)
        self.var_sonido = tk.BooleanVar(value=self.config["sonido"])
        self.var_pitido = tk.BooleanVar(value=self.config["pitido_timers"])
        for i, (texto, var) in enumerate((("Sonido al tomar foto", self.var_sonido),
                                          ("Pitido al iniciar/parar con el mando", self.var_pitido))):
            ctk.CTkSwitch(der, text=texto, variable=var, command=self._guardar_ajustes, font=fuente(13),
                          text_color=TEXTO, fg_color=BORDE, progress_color=VERDE_BORDE,
                          button_color=TEXTO, button_hover_color="#ffffff").grid(row=10 + i, column=0, pady=5, **pad)

        separador(der).grid(row=12, column=0, pady=20, **pad)

        cab, _ = titulo_seccion(der, "Actividad", "Sesión")
        cab.grid(row=13, column=0, pady=(0, 10), **pad)
        self.txt_log = ctk.CTkTextbox(der, height=190, fg_color=TARJETA, border_color=BORDE, border_width=1,
                                      corner_radius=10, text_color=TEXTO, font=fuente(11, familia=MONO),
                                      wrap="word", scrollbar_button_color=BORDE)
        self.txt_log.grid(row=14, column=0, pady=(0, 20), **pad)
        self.txt_log.configure(state="disabled")

        # ---- Barra de estado
        pie = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0, height=30)
        pie.grid(row=2, column=0, columnspan=3, sticky="ew")
        separador(pie).place(relx=0, rely=0, relwidth=1)
        self.lbl_estado = ctk.CTkLabel(pie, text="Capturador  ·  Listo", font=fuente(11), text_color=TENUE)
        self.lbl_estado.pack(side="left", padx=16)
        self.lbl_motor = ctk.CTkLabel(pie, text="Capturador · Silksong", font=fuente(11), text_color=TENUE)
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
        self._guardar()

    def _cambiar_formato(self, valor):
        self.config["formato"] = valor.lower()
        self._guardar()

    def _mostrar_carpeta(self):
        carpeta = self.config["carpeta"]
        self.lbl_carpeta.configure(text=ruta_corta(carpeta, 26))
        self.lbl_carpeta_nombre.configure(text=Path(carpeta).name or carpeta)

    def _timer(self, nombre):
        return next((t for t in self.config["timers"] if t["nombre"] == nombre), None)

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
        for w in self.grilla_timers.winfo_children():
            w.destroy()
        self.tarjetas = {}
        for i, t in enumerate(self.config["timers"]):
            tarjeta = TarjetaTimer(self.grilla_timers, self, t)
            tarjeta.grid(row=i // 2, column=i % 2, sticky="nsew", padx=10, pady=10)
            self.tarjetas[t["nombre"]] = tarjeta
        if not self.config["timers"]:
            vacio = ctk.CTkFrame(self.grilla_timers, fg_color=TARJETA, corner_radius=12, border_width=1,
                                 border_color=BORDE)
            vacio.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
            ctk.CTkLabel(vacio, text="Crea tu primer temporizador (por ejemplo «escribir» o «fotos»).",
                         font=fuente(13), text_color=TENUE).pack(pady=28)
        self._refrescar_tiempos(reprogramar=False)

    def _refrescar_tiempos(self, reprogramar=True):
        ahora = datetime.now()
        en_marcha = []
        for nombre, tarjeta in self.tarjetas.items():
            corriendo = self.registro.corriendo(nombre)
            actual = formato_duracion(self.registro.actual(nombre, ahora))
            tarjeta.actualizar(
                corriendo, actual,
                formato_duracion(self.registro.total_hoy(nombre, ahora)),
                formato_duracion(self.registro.total_semana(nombre, ahora)),
                formato_duracion(self.registro.total(nombre, ahora=ahora)),
            )
            if corriendo:
                en_marcha.append(f"{nombre} {actual}")
        texto = f"{len(en_marcha)} activo" + ("" if len(en_marcha) == 1 else "s")
        if self.ins_activos.cget("text") != texto.upper():
            self.ins_activos.configure(text=texto.upper(), text_color=VERDE if en_marcha else TENUE)
        # El título se ve en la barra de tareas sin abrir la ventana.
        titulo = f"▶ {', '.join(en_marcha)} — {TITULO}" if en_marcha else TITULO
        if self.root.title() != titulo:
            self.root.title(titulo)
        if reprogramar:
            self.root.after(500, self._refrescar_tiempos)

    def _latido(self):
        self.registro.latido()
        self.root.after(LATIDO_CADA_MS, self._latido)

    # ------------------------------------------------------------------ miniaturas

    def _cargar_miniaturas(self):
        """Hilo: lee las fotos más recientes de la carpeta al abrir la app."""
        carpeta = Path(self.config["carpeta"]).expanduser()
        try:
            archivos = sorted((p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES_FOTO),
                              key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_MINIATURAS]
        except OSError:
            archivos = []
        lista = []
        for ruta in archivos:
            try:
                with Image.open(ruta) as img:
                    img.draft("RGB", (TAM_MINIATURA[0] * 2, TAM_MINIATURA[1] * 2))  # acelera JPG
                    lista.append((ruta, hacer_miniatura(img)))
            except Exception:
                continue
        self.eventos.put(("miniaturas", lista))

    def _dibujar_miniaturas(self):
        for w in self.grilla_fotos.winfo_children():
            w.destroy()
        for i, (ruta, img) in enumerate(self.miniaturas):
            celda = ctk.CTkFrame(self.grilla_fotos, fg_color=TARJETA, corner_radius=8, border_width=1,
                                 border_color=BORDE)
            celda.grid(row=i // 2, column=i % 2, sticky="nsew", padx=5, pady=5)
            foto = ctk.CTkLabel(celda, text="", image=ctk.CTkImage(img, size=TAM_MINIATURA), cursor="hand2")
            foto.pack(padx=4, pady=(4, 0))
            etiqueta = ctk.CTkLabel(celda, text=etiqueta_foto(ruta)[:24], font=fuente(10), text_color=TENUE,
                                    anchor="w", height=20)
            etiqueta.pack(fill="x", padx=8, pady=(0, 4))
            for w in (foto, etiqueta):
                w.bind("<Button-1>", lambda e, r=ruta: abrir(r))
        if not self.miniaturas:
            ctk.CTkLabel(self.grilla_fotos, text="Aquí aparecerán\ntus fotos recientes.", font=fuente(12),
                         text_color=TENUE).grid(row=0, column=0, columnspan=2, pady=40)
        self.ins_fotos.configure(text=str(len(self.miniaturas)))

    # ------------------------------------------------------------------ eventos

    def _procesar_eventos(self):
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
                    self.lbl_motor.configure(text=f"Captura: {evento[1]}  ·  Capturador · Silksong")
                elif tipo == "error":
                    self.escucha_error = evento[1]
                    self.pastilla_mando.configure(text="●  Mando no disponible", text_color=ROJO,
                                                  fg_color=ROJO_FONDO)
                    self.log(f"[!] {evento[1]}")
                elif tipo == "timer":
                    self._alternar_timer(evento[1], evento[2], desde_mando=True)
                elif tipo == "combo":
                    self._combo_grabado(evento[1])
                elif tipo == "miniaturas":
                    self.miniaturas = evento[1] + self.miniaturas
                    del self.miniaturas[MAX_MINIATURAS:]
                    self._dibujar_miniaturas()
                elif tipo == "miniatura":
                    self.miniaturas.insert(0, (evento[1], evento[2]))
                    del self.miniaturas[MAX_MINIATURAS:]
                    self._dibujar_miniaturas()
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
        cuerpo = ctk.CTkFrame(d, fg_color="transparent")
        cuerpo.pack(padx=30, pady=24)
        ctk.CTkLabel(cuerpo, text="🎮", font=fuente(40)).pack()
        ctk.CTkLabel(cuerpo, text=titulo, font=fuente(16, "bold"), text_color=TEXTO).pack(pady=(6, 0))
        ctk.CTkLabel(cuerpo, text="Presiona el botón (o mantén una combinación) en el mando.\n"
                                  "Al soltar todo, se guardará.",
                     font=fuente(13), text_color=TENUE, justify="center").pack(pady=(6, 16))
        boton(cuerpo, "Cancelar", self._cancelar_grabacion, "normal", width=120).pack()
        d.protocol("WM_DELETE_WINDOW", self._cancelar_grabacion)
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
        for dueno in self.config["atajos"] + self.config["timers"]:
            if dueno.get("botones") and cap.nombres_a_mascara(dueno["botones"]) == mascara:
                Dialogo.mostrar(self.root, "Combinación ocupada",
                                f"{cap.texto_combo(nombres)} ya está asignado a «{dueno['nombre']}».")
                return
        if len(nombres) == 1 and not Dialogo.confirmar(
                self.root, f"Detectado: {nombres[0]}",
                "Un solo botón también lo usa el juego. Una combinación como BACK + RB evita "
                "disparos accidentales.\n\n¿Usarlo de todos modos?", si="Usarlo"):
            return
        al_terminar(nombres)

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
        nombre = self._pedir_nombre("Nuevo atajo de foto", "¿Cómo se llamará este atajo?",
                                    f"foto{len(self.config['atajos']) + 1}")
        if not nombre:
            return

        def listo(botones):
            self.config["atajos"].append({"nombre": nombre, "botones": botones})
            self._guardar()
            self.escucha.recargar()
            self._refrescar_fotos()
            self.log(f"Atajo de foto '{nombre}' = {cap.texto_combo(botones)}")
        self._grabar_combo("Atajo de foto", listo)

    def borrar_foto(self, nombre):
        if not Dialogo.confirmar(self.root, "Borrar atajo", f"¿Borrar el atajo «{nombre}»?",
                                 si="Borrar", estilo="rojo"):
            return
        self.config["atajos"] = [a for a in self.config["atajos"] if a["nombre"] != nombre]
        self._guardar()
        self.escucha.recargar()
        self._refrescar_fotos()

    def cambiar_carpeta(self):
        nueva = filedialog.askdirectory(initialdir=self.config["carpeta"], title="Carpeta para las fotos")
        if nueva:
            self.config["carpeta"] = os.path.normpath(nueva)
            self._mostrar_carpeta()
            self._guardar()
            self.miniaturas = []
            self._dibujar_miniaturas()
            threading.Thread(target=self._cargar_miniaturas, daemon=True).start()

    def abrir_fotos(self):
        carpeta = os.path.expanduser(self.config["carpeta"])
        os.makedirs(carpeta, exist_ok=True)
        abrir(carpeta)

    # ------------------------------------------------------------------ timers

    def nuevo_timer(self):
        nombre = self._pedir_nombre("Nuevo temporizador", "Nombre de la actividad (por ejemplo: escribir, fotos).", "")
        if not nombre:
            return
        self.config["timers"].append({"nombre": nombre})
        self._guardar()
        self._refrescar_timers()
        if Dialogo.confirmar(self.root, "Botón del mando",
                             f"¿Asignar un botón del mando para iniciar y parar «{nombre}»?", si="Asignar"):
            self.asignar_boton_timer(nombre)

    def asignar_boton_timer(self, nombre):
        timer = self._timer(nombre)

        def listo(botones):
            timer["botones"] = botones
            self._guardar()
            self.escucha.recargar()
            self._refrescar_timers()
            self.log(f"Temporizador '{nombre}' = {cap.texto_combo(botones)}")
        self._grabar_combo(f"Botón para «{nombre}»", listo)

    def quitar_boton_timer(self, nombre):
        self._timer(nombre).pop("botones", None)
        self._guardar()
        self.escucha.recargar()
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
        self._alternar_timer(nombre, datetime.now())

    def _alternar_timer(self, nombre, momento, desde_mando=False):
        if self._timer(nombre) is None:
            return
        corriendo, duracion = self.registro.alternar(nombre, momento)
        if corriendo:
            self.log(f"▶ '{nombre}' iniciado")
        else:
            self.log(f"■ '{nombre}' detenido: {formato_duracion(duracion.total_seconds())}")
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
        self.escucha.detener()
        self.escucha.join(timeout=3)
        self.root.destroy()


# --------------------------------------------------------------------------
# Inicio
# --------------------------------------------------------------------------

_mutex = None


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
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CapturadorSilksong")
        except Exception:
            pass
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    if ya_esta_abierta():
        root.withdraw()
        messagebox.showinfo(TITULO, "La app ya está abierta (revisa la barra de tareas).")
        root.destroy()
        return

    def al_fallar(tipo, valor, tb):
        registrar_error("".join(traceback.format_exception(tipo, valor, tb)))
        messagebox.showerror(TITULO, f"Ocurrió un error:\n{valor}\n\nDetalles en {LOG_ERRORES.name}")
    root.report_callback_exception = al_fallar

    try:
        App(root)
    except Exception as e:
        registrar_error(traceback.format_exc())
        messagebox.showerror(TITULO, f"No se pudo iniciar:\n{e}\n\nDetalles en {LOG_ERRORES.name}")
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
