"""
Ventana de Capturador Silksong: fotos y temporizadores con el mando.

La ventana nunca se pone al frente sola ni toma el foco, así que se puede
dejar abierta (o minimizada) mientras juegas o escribes.
"""

import ctypes
import os
import queue
import threading
import time
import traceback
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import capturador as cap
from tiempos import RegistroTiempos, formato_duracion

CARPETA = cap.CARPETA_SCRIPT
ICONO = CARPETA / "icono.ico"
LOG_ERRORES = CARPETA / "errores.log"
TITULO = "Capturador Silksong"
LATIDO_CADA_MS = 30_000


def registrar_error(texto):
    with open(LOG_ERRORES, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{texto}\n")


def ruta_corta(ruta, maximo=55):
    return ruta if len(ruta) <= maximo else "…" + ruta[-(maximo - 1):]


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

        guardador = cap.Guardador(self.config, aviso=lambda t: self._avisar("log", t.strip()))
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

        root.title(TITULO)
        root.geometry("700x660")
        root.minsize(620, 560)
        if ICONO.exists():
            try:
                root.iconbitmap(default=str(ICONO))
            except tk.TclError:
                pass

        self._construir_ui()
        self._refrescar_listas()

        for actividad, duracion in self.registro.recuperadas:
            self.log(f"Recuperado '{actividad}' de un cierre inesperado: {formato_duracion(duracion.total_seconds())}")

        self.escucha.start()
        root.protocol("WM_DELETE_WINDOW", self.cerrar)
        root.after(100, self._procesar_eventos)
        root.after(500, self._refrescar_tiempos)
        root.after(LATIDO_CADA_MS, self._latido)

    # ------------------------------------------------------------------ UI

    def _construir_ui(self):
        r = self.root
        estilo = ttk.Style()
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")
        estilo.configure("Treeview", rowheight=24)
        estilo.configure("Corriendo.TLabel", foreground="#1a7f37")

        principal = ttk.Frame(r, padding=10)
        principal.pack(fill="both", expand=True)

        # Estado
        estado = ttk.Frame(principal)
        estado.pack(fill="x")
        self.lbl_mando = ttk.Label(estado, text="Mando: buscando...")
        self.lbl_mando.pack(side="left")
        self.lbl_motor = ttk.Label(estado, text="")
        self.lbl_motor.pack(side="left", padx=15)
        ttk.Button(estado, text="Abrir carpeta de fotos", command=self.abrir_fotos).pack(side="right")

        # Temporizadores
        ft = ttk.LabelFrame(principal, text="Temporizadores", padding=8)
        ft.pack(fill="both", expand=True, pady=(10, 0))
        cols = ("atajo", "actual", "hoy", "semana", "total")
        self.tree_timers = ttk.Treeview(ft, columns=cols, height=5, selectmode="browse")
        self.tree_timers.heading("#0", text="Actividad")
        self.tree_timers.column("#0", width=130)
        for c, texto, ancho in (("atajo", "Botón", 120), ("actual", "En marcha", 85),
                                ("hoy", "Hoy", 75), ("semana", "Semana", 75), ("total", "Total", 80)):
            self.tree_timers.heading(c, text=texto)
            self.tree_timers.column(c, width=ancho, anchor="center")
        self.tree_timers.tag_configure("corriendo", foreground="#1a7f37")
        self.tree_timers.pack(fill="both", expand=True)
        self.tree_timers.bind("<Double-1>", lambda e: self.alternar_timer_seleccionado())

        bt = ttk.Frame(ft)
        bt.pack(fill="x", pady=(6, 0))
        ttk.Button(bt, text="Iniciar / Parar", command=self.alternar_timer_seleccionado).pack(side="left")
        ttk.Button(bt, text="Nuevo", command=self.nuevo_timer).pack(side="left", padx=4)
        ttk.Button(bt, text="Asignar botón", command=self.asignar_boton_timer).pack(side="left")
        ttk.Button(bt, text="Quitar botón", command=self.quitar_boton_timer).pack(side="left", padx=4)
        ttk.Button(bt, text="Borrar", command=self.borrar_timer).pack(side="left")
        ttk.Button(bt, text="Ver historial", command=self.abrir_historial).pack(side="right")
        self.var_pitido = tk.BooleanVar(value=self.config["pitido_timers"])
        ttk.Checkbutton(ft, text="Pitido al iniciar/parar con el mando", variable=self.var_pitido,
                        command=self._guardar_ajustes).pack(anchor="w", pady=(6, 0))

        # Fotos
        ff = ttk.LabelFrame(principal, text="Fotos", padding=8)
        ff.pack(fill="x", pady=(10, 0))
        self.tree_fotos = ttk.Treeview(ff, columns=("atajo",), height=3, selectmode="browse")
        self.tree_fotos.heading("#0", text="Atajo")
        self.tree_fotos.column("#0", width=130)
        self.tree_fotos.heading("atajo", text="Botón")
        self.tree_fotos.column("atajo", width=200, anchor="center")
        self.tree_fotos.pack(fill="x")

        bf = ttk.Frame(ff)
        bf.pack(fill="x", pady=(6, 0))
        ttk.Button(bf, text="Agregar atajo", command=self.agregar_foto).pack(side="left")
        ttk.Button(bf, text="Borrar", command=self.borrar_foto).pack(side="left", padx=4)

        ajustes = ttk.Frame(ff)
        ajustes.pack(fill="x", pady=(6, 0))
        self.var_sonido = tk.BooleanVar(value=self.config["sonido"])
        ttk.Checkbutton(ajustes, text="Sonido al tomar foto", variable=self.var_sonido,
                        command=self._guardar_ajustes).pack(side="left")
        ttk.Label(ajustes, text="Formato:").pack(side="left", padx=(15, 4))
        self.var_formato = tk.StringVar(value=self.config["formato"])
        cb = ttk.Combobox(ajustes, textvariable=self.var_formato, values=("png", "jpg"),
                          width=5, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._guardar_ajustes())

        carpeta = ttk.Frame(ff)
        carpeta.pack(fill="x", pady=(6, 0))
        ttk.Label(carpeta, text="Carpeta:").pack(side="left")
        self.lbl_carpeta = ttk.Label(carpeta, text=ruta_corta(self.config["carpeta"]), foreground="#555")
        self.lbl_carpeta.pack(side="left", padx=4)
        ttk.Button(carpeta, text="Cambiar...", command=self.cambiar_carpeta).pack(side="right")

        # Registro de actividad
        fl = ttk.LabelFrame(principal, text="Actividad", padding=4)
        fl.pack(fill="both", pady=(10, 0))
        self.txt_log = tk.Text(fl, height=6, state="disabled", wrap="word",
                               font=("Consolas", 9), relief="flat")
        self.txt_log.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ util

    def log(self, texto):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"{datetime.now():%H:%M:%S}  {texto}\n")
        lineas = int(self.txt_log.index("end-1c").split(".")[0])
        if lineas > 200:
            self.txt_log.delete("1.0", f"{lineas - 200}.0")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _guardar(self):
        cap.guardar_config(self.config)

    def _guardar_ajustes(self):
        self.config["sonido"] = self.var_sonido.get()
        self.config["formato"] = self.var_formato.get()
        self.config["pitido_timers"] = self.var_pitido.get()
        self._guardar()

    def _seleccion(self, tree):
        sel = tree.selection()
        return sel[0] if sel else None

    def _timer(self, nombre):
        return next((t for t in self.config["timers"] if t["nombre"] == nombre), None)

    def _refrescar_listas(self):
        self.tree_fotos.delete(*self.tree_fotos.get_children())
        for a in self.config["atajos"]:
            self.tree_fotos.insert("", "end", iid=a["nombre"], text=a["nombre"],
                                   values=(cap.texto_combo(a["botones"]),))
        seleccion = self._seleccion(self.tree_timers)
        self.tree_timers.delete(*self.tree_timers.get_children())
        for t in self.config["timers"]:
            boton = cap.texto_combo(t["botones"]) if t.get("botones") else "(sin botón)"
            self.tree_timers.insert("", "end", iid=t["nombre"], text=t["nombre"],
                                    values=(boton, "", "", "", ""))
        if seleccion and self.tree_timers.exists(seleccion):
            self.tree_timers.selection_set(seleccion)
        self._refrescar_tiempos(reprogramar=False)

    def _refrescar_tiempos(self, reprogramar=True):
        ahora = datetime.now()
        en_marcha = []
        for t in self.config["timers"]:
            n = t["nombre"]
            if not self.tree_timers.exists(n):
                continue
            corriendo = self.registro.corriendo(n)
            actual = formato_duracion(self.registro.actual(n, ahora)) if corriendo else "-"
            valores = list(self.tree_timers.item(n, "values"))
            valores[1:] = [
                ("● " + actual) if corriendo else actual,
                formato_duracion(self.registro.total_hoy(n, ahora)),
                formato_duracion(self.registro.total_semana(n, ahora)),
                formato_duracion(self.registro.total(n, ahora=ahora)),
            ]
            self.tree_timers.item(n, values=valores, tags=("corriendo",) if corriendo else ())
            if corriendo:
                en_marcha.append(f"{n} {actual}")
        # El título se ve en la barra de tareas sin abrir la ventana.
        titulo = f"▶ {', '.join(en_marcha)} — {TITULO}" if en_marcha else TITULO
        if self.root.title() != titulo:
            self.root.title(titulo)
        if reprogramar:
            self.root.after(500, self._refrescar_tiempos)

    def _latido(self):
        self.registro.latido()
        self.root.after(LATIDO_CADA_MS, self._latido)

    # ------------------------------------------------------------------ eventos

    def _procesar_eventos(self):
        try:
            while True:
                evento = self.eventos.get_nowait()
                tipo = evento[0]
                if tipo == "log":
                    self.log(evento[1])
                elif tipo == "mando":
                    self.lbl_mando.configure(
                        text="Mando: conectado" if evento[1] else "Mando: no detectado",
                        style="Corriendo.TLabel" if evento[1] else "TLabel")
                elif tipo == "motor":
                    self.lbl_motor.configure(text=f"Captura: {evento[1]}")
                elif tipo == "error":
                    self.escucha_error = evento[1]
                    self.lbl_mando.configure(text="Mando: no disponible")
                    self.log(f"[!] {evento[1]}")
                elif tipo == "timer":
                    self._alternar_timer(evento[1], evento[2], desde_mando=True)
                elif tipo == "combo":
                    self._combo_grabado(evento[1])
        except queue.Empty:
            pass
        self.root.after(50, self._procesar_eventos)

    # ------------------------------------------------------------------ grabar combo

    def _grabar_combo(self, titulo, al_terminar):
        if self.escucha_error:
            messagebox.showerror(TITULO, self.escucha_error)
            return
        self._al_grabar = al_terminar
        d = tk.Toplevel(self.root)
        d.title(titulo)
        d.transient(self.root)
        d.resizable(False, False)
        ttk.Label(d, text="Presiona el botón (o mantén una combinación) en el mando.\n"
                          "Al soltar todo, se guardará.",
                  padding=20, justify="center").pack()
        ttk.Button(d, text="Cancelar", command=self._cancelar_grabacion).pack(pady=(0, 15))
        d.protocol("WM_DELETE_WINDOW", self._cancelar_grabacion)
        d.grab_set()
        self._dialogo_grabar = d
        self.escucha.grabar_combo()

    def _cancelar_grabacion(self):
        self.escucha.cancelar_grabacion()
        self._cerrar_dialogo()
        self._al_grabar = None

    def _cerrar_dialogo(self):
        if self._dialogo_grabar is not None:
            self._dialogo_grabar.grab_release()
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
                messagebox.showwarning(TITULO, f"{cap.texto_combo(nombres)} ya está asignado a '{dueno['nombre']}'.")
                return
        if len(nombres) == 1 and not messagebox.askyesno(
                TITULO, f"Detectado: {nombres[0]}\n\nUn solo botón también lo usa el juego. "
                        "Una combinación como BACK + RB evita disparos accidentales.\n\n¿Usarlo de todos modos?"):
            return
        al_terminar(nombres)

    def _pedir_nombre(self, titulo, sugerido):
        nombre = simpledialog.askstring(TITULO, titulo, initialvalue=sugerido, parent=self.root)
        if not nombre or not nombre.strip():
            return None
        nombre = nombre.strip()
        usados = {a["nombre"] for a in self.config["atajos"]} | {t["nombre"] for t in self.config["timers"]}
        if nombre in usados:
            messagebox.showwarning(TITULO, f"Ya existe algo llamado '{nombre}'.")
            return None
        return nombre

    # ------------------------------------------------------------------ fotos

    def agregar_foto(self):
        nombre = self._pedir_nombre("Nombre del atajo de foto:", f"foto{len(self.config['atajos']) + 1}")
        if not nombre:
            return

        def listo(botones):
            self.config["atajos"].append({"nombre": nombre, "botones": botones})
            self._guardar()
            self.escucha.recargar()
            self._refrescar_listas()
            self.log(f"Atajo de foto '{nombre}' = {cap.texto_combo(botones)}")
        self._grabar_combo("Atajo de foto", listo)

    def borrar_foto(self):
        nombre = self._seleccion(self.tree_fotos)
        if not nombre or not messagebox.askyesno(TITULO, f"¿Borrar el atajo '{nombre}'?"):
            return
        self.config["atajos"] = [a for a in self.config["atajos"] if a["nombre"] != nombre]
        self._guardar()
        self.escucha.recargar()
        self._refrescar_listas()

    def cambiar_carpeta(self):
        nueva = filedialog.askdirectory(initialdir=self.config["carpeta"], title="Carpeta para las fotos")
        if nueva:
            self.config["carpeta"] = os.path.normpath(nueva)
            self.lbl_carpeta.configure(text=ruta_corta(self.config["carpeta"]))
            self._guardar()

    def abrir_fotos(self):
        carpeta = os.path.expanduser(self.config["carpeta"])
        os.makedirs(carpeta, exist_ok=True)
        os.startfile(carpeta)

    # ------------------------------------------------------------------ timers

    def nuevo_timer(self):
        nombre = self._pedir_nombre("Nombre de la actividad (ej. fotos, escribir):", "")
        if not nombre:
            return
        self.config["timers"].append({"nombre": nombre})
        self._guardar()
        self._refrescar_listas()
        self.tree_timers.selection_set(nombre)
        if messagebox.askyesno(TITULO, f"¿Asignar un botón del mando para iniciar/parar '{nombre}'?"):
            self.asignar_boton_timer()

    def asignar_boton_timer(self):
        nombre = self._seleccion(self.tree_timers)
        if not nombre:
            messagebox.showinfo(TITULO, "Selecciona un temporizador primero.")
            return
        timer = self._timer(nombre)

        def listo(botones):
            timer["botones"] = botones
            self._guardar()
            self.escucha.recargar()
            self._refrescar_listas()
            self.log(f"Temporizador '{nombre}' = {cap.texto_combo(botones)}")
        self._grabar_combo(f"Botón para '{nombre}'", listo)

    def quitar_boton_timer(self):
        nombre = self._seleccion(self.tree_timers)
        if nombre:
            self._timer(nombre).pop("botones", None)
            self._guardar()
            self.escucha.recargar()
            self._refrescar_listas()

    def borrar_timer(self):
        nombre = self._seleccion(self.tree_timers)
        if not nombre or not messagebox.askyesno(
                TITULO, f"¿Borrar el temporizador '{nombre}'?\n\nEl historial ya guardado se conserva."):
            return
        if self.registro.corriendo(nombre):
            self._alternar_timer(nombre, datetime.now())
        self.config["timers"] = [t for t in self.config["timers"] if t["nombre"] != nombre]
        self._guardar()
        self.escucha.recargar()
        self._refrescar_listas()

    def alternar_timer_seleccionado(self):
        nombre = self._seleccion(self.tree_timers)
        if nombre:
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
            messagebox.showinfo(TITULO, "Todavía no hay sesiones guardadas.")
            return
        os.startfile(self.registro.archivo)

    # ------------------------------------------------------------------ cerrar

    def cerrar(self):
        for nombre, duracion in self.registro.parar_todos().items():
            if duracion is not None:
                self.log(f"■ '{nombre}' detenido al cerrar: {formato_duracion(duracion.total_seconds())}")
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


def preparar_windows():
    if os.name != "nt":
        return
    try:
        # Que la barra de tareas muestre nuestro icono y no el de Python.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CapturadorSilksong")
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # texto nítido en pantallas con escala
    except Exception:
        pass


def main():
    preparar_windows()
    root = tk.Tk()
    if ya_esta_abierta():
        root.withdraw()
        messagebox.showinfo(TITULO, "La app ya está abierta (revisa la barra de tareas).")
        root.destroy()
        return

    def al_fallar(tipo, valor, tb):
        texto = "".join(traceback.format_exception(tipo, valor, tb))
        registrar_error(texto)
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
