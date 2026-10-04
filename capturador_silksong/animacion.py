"""
Grabación de animaciones: secuencias de imágenes a 60 fps.

Cómo evita frenar el juego:
- Un hilo captura a ritmo fijo (60 fps). Si la pantalla no cambió en ese
  cuadro, repite el fotograma anterior sin copiarlo.
- Los fotogramas esperan en RAM y unos hilos de prioridad mínima los van
  codificando (Pillow suelta el GIL al comprimir, así que trabajan en
  paralelo de verdad), durante la grabación y después de parar.
- Si la RAM usada llega al límite, la grabación se detiene sola.

Archivos: <carpeta>/anim01/<sufijo>-anim01-001.png (o .jpg / .webp), ...
"""

import ctypes
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

import capturador as cap

MB = 1024 * 1024
PATRON_CARPETA = re.compile(r"^anim(\d+)$", re.IGNORECASE)
AVISAR_CADA = 15  # fotogramas entre avisos de progreso


def memoria_total():
    """RAM total del equipo en bytes (4 GB si no se puede saber)."""
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        estado = MEMORYSTATUSEX()
        estado.dwLength = ctypes.sizeof(estado)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
            return estado.ullTotalPhys
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 4 * 1024 * MB


def limite_por_defecto():
    """35 % de la RAM, máximo 6 GB."""
    return int(min(6 * 1024 * MB, memoria_total() * 0.35))


def nueva_carpeta(base):
    """Crea la siguiente carpeta animNN libre y devuelve (ruta, numero)."""
    base.mkdir(parents=True, exist_ok=True)
    usados = [int(m.group(1)) for p in base.iterdir() if p.is_dir() and (m := PATRON_CARPETA.match(p.name))]
    numero = max(usados, default=0) + 1
    while True:
        ruta = base / f"anim{numero:02d}"
        try:
            ruta.mkdir()
            return ruta, numero
        except FileExistsError:
            numero += 1


class Limitador:
    """Cuántos cuadros se codifican a la vez; el límite se relee siempre (cambia con el modo)."""

    def __init__(self, limite):
        self._limite = limite
        self._activos = 0
        self._cond = threading.Condition()

    def __enter__(self):
        with self._cond:
            while self._activos >= self._limite():
                self._cond.wait(timeout=0.2)
            self._activos += 1

    def __exit__(self, *exc):
        with self._cond:
            self._activos -= 1
            self._cond.notify_all()


def _tam(datos):
    tipo, obj = datos
    return obj.nbytes if tipo == "bgra" else len(obj.raw)


class GrabadorAnimacion:
    def __init__(self, config, avisar):
        self.base = Path(config["carpeta"]).expanduser()
        self.sufijo = cap.limpiar_sufijo(config.get("sufijo"))
        self.ext = cap.extension(config.get("formato"))  # fijo para toda la animación
        self.fps = int(config.get("anim_fps", 60))
        limite_mb = config.get("anim_limite_mb")
        self.limite = int(limite_mb) * MB if limite_mb else limite_por_defecto()
        self.motor = config.get("motor", "auto")
        self.monitor = config.get("monitor", 1)
        self.avisar = avisar  # función(*evento)
        self.config = config  # se lee "prioridad" en vivo
        self.resolucion = config.get("resolucion", "nativa")  # fija para toda la animación

        self.carpeta = None
        self.numero = None
        self.total = 0
        self._parar = threading.Event()
        self._lock = threading.Lock()
        self._bytes = 0
        self._hechos = 0
        self._unicos = 0
        self._hilo = None
        cpus = os.cpu_count() or 4
        self._hilos = {"juego": max(2, min(4, cpus // 3)), "grabacion": max(2, min(8, cpus - 1))}
        self._pool = ThreadPoolExecutor(max_workers=self._hilos["grabacion"])
        self._limitador = Limitador(lambda: self._hilos.get(self._modo(), self._hilos["juego"]))

    # ------------------------------------------------------------------ control

    def iniciar(self):
        self.carpeta, self.numero = nueva_carpeta(self.base)
        self._hilo = threading.Thread(target=self._trabajar, daemon=True)
        self._hilo.start()

    def detener(self):
        self._parar.set()

    @property
    def grabando(self):
        return self._hilo is not None and self._hilo.is_alive() and not self._parar.is_set()

    def ocupado(self):
        """True mientras graba o todavía está guardando fotogramas."""
        return self._hilo is not None and self._hilo.is_alive()

    def _modo(self):
        return self.config.get("prioridad", "juego")

    # ------------------------------------------------------------------ nombres

    def _ruta(self, indice, ancho=3):
        return self.carpeta / f"{self.sufijo}-anim{self.numero:02d}-{indice + 1:0{ancho}d}.{self.ext}"

    # ------------------------------------------------------------------ trabajo

    def _codificar(self, indice, datos, tam):
        try:
            with self._limitador:
                self._guardar_cuadro(indice, datos)
        finally:
            with self._lock:
                self._bytes -= tam
                self._hechos += 1

    def _guardar_cuadro(self, indice, datos):
        cap.prioridad_hilo(self._modo())
        img = cap.ajustar_resolucion(cap.Capturador.a_imagen(datos), self.resolucion)
        cap.guardar_imagen(img, self._ruta(indice), self.config, rapido=True)

    def _trabajar(self):
        winmm = ctypes.windll.winmm if os.name == "nt" else None
        if winmm:
            winmm.timeBeginPeriod(1)  # sleep preciso (1 ms) mientras graba
        try:
            mapa, futuros, primero, motivo = self._capturar()
        finally:
            if winmm:
                winmm.timeEndPeriod(1)

        self.total = len(mapa)
        if self.total == 0:
            try:
                self.carpeta.rmdir()
            except OSError:
                pass
        miniatura = None
        if primero is not None:
            try:
                miniatura = cap.Capturador.a_imagen(primero)
            except Exception:
                pass
        self.avisar("anim_fin", self.carpeta, miniatura, self.total, motivo)

        # Esperar la codificación avisando el avance.
        pendientes = set(futuros)
        while pendientes:
            _, pendientes = wait(pendientes, timeout=0.5)
            self.avisar("anim_guardando", self.carpeta, self._hechos, self._unicos)
        self._pool.shutdown(wait=True)
        errores = [f.exception() for f in futuros if f.exception() is not None]

        # Fotogramas repetidos: copiar el archivo del original.
        for i, origen in enumerate(mapa):
            if origen != i:
                shutil.copyfile(self._ruta(origen), self._ruta(i))

        # Más de 999 fotogramas: renombrar con más dígitos para que ordenen bien.
        ancho = len(str(self.total))
        if ancho > 3:
            for i in range(self.total):
                actual = self._ruta(i)
                nuevo = self._ruta(i, ancho)
                if actual != nuevo:
                    actual.rename(nuevo)

        self.avisar("anim_guardada", self.carpeta, self.total, self.total / self.fps,
                    str(errores[0]) if errores else None)

    def _capturar(self):
        """Bucle de captura a ritmo fijo. Devuelve (mapa, futuros, primer_fotograma, motivo)."""
        try:
            capt = cap.Capturador(self.motor, self.monitor)  # propio de este hilo
        except Exception as e:
            return [], [], None, f"error: {e}"

        cap.prioridad_hilo(self._modo(), captura=True)
        intervalo = 1.0 / self.fps
        mapa = []      # mapa[i] = índice del fotograma original (i si es nuevo)
        futuros = []
        primero = None
        ultimo_nuevo = None
        motivo = "detenida"
        t0 = time.perf_counter()

        def emitir(datos):
            nonlocal ultimo_nuevo, primero
            indice = len(mapa)
            if datos is None:
                mapa.append(ultimo_nuevo)
                return
            tam = _tam(datos)
            with self._lock:
                self._bytes += tam
                self._unicos += 1
            mapa.append(indice)
            ultimo_nuevo = indice
            if primero is None:
                primero = datos
            futuros.append(self._pool.submit(self._codificar, indice, datos, tam))

        while not self._parar.is_set():
            objetivo = t0 + len(mapa) * intervalo
            espera = objetivo - time.perf_counter()
            if espera > 0:
                time.sleep(espera)

            try:
                datos = capt.fotograma() if ultimo_nuevo is not None else capt.tomar()
            except Exception as e:
                motivo = f"error: {e}"
                break
            emitir(datos)

            # Si la captura se atrasó, rellenar los cuadros perdidos con el último.
            atraso = int((time.perf_counter() - t0) / intervalo) - len(mapa)
            for _ in range(max(0, atraso)):
                emitir(None)

            if len(mapa) % AVISAR_CADA == 0:
                self.avisar("anim_progreso", len(mapa), time.perf_counter() - t0)
                cap.prioridad_hilo(self._modo(), captura=True)  # sigue el modo si se cambia
            if self._bytes > self.limite:
                motivo = "límite de memoria"
                break

        self._parar.set()
        return mapa, futuros, primero, motivo
