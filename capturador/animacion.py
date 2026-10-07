"""
Grabación de animaciones a 60 fps.

Para que se vea fluida:
- Con dxcam se toma CADA cuadro que el juego muestra, en el momento en que
  aparece (se revisa cada ~1 ms), en vez de mirar la pantalla a horas fijas.
  Cada cuadro nuevo se guarda una vez; si el juego tarda más (escena a 30 fps,
  pantalla quieta), el cuadro anterior se repite para que la animación dure
  lo mismo que en la realidad. Si el monitor va a más de 60 Hz, se queda con
  un cuadro por cada 1/60 s.
- La compresión ocurre en PROCESOS aparte (trabajador.py). Pillow mantiene el
  GIL al comprimir WebP/JPG y, en el mismo proceso, eso congelaba la captura y
  hacía que se perdieran cuadros (la animación se veía cortada).
- El hilo de captura tiene prioridad alta: hace muy poco trabajo por cuadro.
- No hay límite de duración. Si la PC no alcanza a guardar al ritmo del juego
  y la RAM pendiente llega al límite, se repite el cuadro anterior en vez de
  guardar uno nuevo
  (como si el juego se trabara un instante) hasta que se libere. La grabación
  nunca se detiene sola.

Fotos y animaciones comparten la numeración del sufijo:
  doric-001.webp, doric-002.webp, doric-anim_003/doric-anim_003-001.webp …,
  doric-004.webp
AVIF animado: doric-anim_003.avif (un solo archivo que se reproduce como un
GIF pero muchísimo más ligero: AV1 aprovecha lo que se repite entre cuadros).
"""

import ctypes
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
from concurrent.futures import wait
from pathlib import Path

from PIL import Image, features

import capturador as cap
import trabajador

MB = 1024 * 1024
# Carpetas de animación: las nuevas (doric-anim_003) y las de versiones anteriores (anim01).
PATRON_CARPETA = re.compile(r"^(?:anim\d+|.+-anim_\d+)$", re.IGNORECASE)
AVISAR_CADA_SEG = 0.25
TOLERANCIA = 0.003  # s: variación normal entre cuadros del juego que se acepta como "a tiempo"

_cpus = os.cpu_count() or 4
# Cuántos cuadros se comprimen a la vez según la prioridad elegida.
HILOS = {"juego": max(2, min(4, _cpus // 3)), "grabacion": max(2, min(8, _cpus - 1))}


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


def nueva_carpeta(base, sufijo):
    """Crea <sufijo>-anim_NNN con el siguiente número compartido con las fotos."""
    base.mkdir(parents=True, exist_ok=True)
    while True:
        numero = cap.reservar_numero(base, sufijo)
        ruta = base / f"{sufijo}-anim_{numero:03d}"
        try:
            ruta.mkdir()
            return ruta, numero
        except FileExistsError:
            continue


class Limitador:
    """Cuántas tareas a la vez; el límite se relee siempre (cambia con el modo)."""

    def __init__(self, limite):
        self._limite = limite
        self._activos = 0
        self._cond = threading.Condition()

    def tomar(self):
        with self._cond:
            while self._activos >= self._limite():
                self._cond.wait(timeout=0.2)
            self._activos += 1

    def soltar(self):
        with self._cond:
            self._activos -= 1
            self._cond.notify_all()


class BancoMemoria:
    """Bloques de memoria compartida que se reutilizan entre cuadros.

    Cada cuadro capturado se pasa aquí enseguida para que el sistema recicle la
    memoria normal del siguiente cuadro (pedir 8 MB nuevos por cuadro mientras
    la cola crece llegó a tardar 20 ms y retrasaba la captura).
    """

    def __init__(self):
        self._bloques = {}  # nombre -> (shm, vista ctypes); las vistas solo viven aquí
        self._libres = []
        self._lock = threading.Lock()

    def obtener(self, tam):
        """Devuelve (nombre, dirección) de un bloque libre de al menos `tam` bytes."""
        from multiprocessing import shared_memory
        with self._lock:
            for i, nombre in enumerate(self._libres):
                shm, vista = self._bloques[nombre]
                if shm.size >= tam:
                    del self._libres[i]
                    return nombre, ctypes.addressof(vista)
        shm = shared_memory.SharedMemory(create=True, size=tam)
        vista = (ctypes.c_char * shm.size).from_buffer(shm.buf)
        with self._lock:
            self._bloques[shm.name] = (shm, vista)
        return shm.name, ctypes.addressof(vista)

    def devolver(self, nombre):
        with self._lock:
            self._libres.append(nombre)

    def cerrar(self):
        with self._lock:
            bloques = list(self._bloques.values())
            self._bloques.clear()
            self._libres.clear()
        shms = [shm for shm, _ in bloques]
        del bloques  # suelta las vistas: si no, la memoria no se puede cerrar
        for shm in shms:
            cap.liberar_memoria(shm)


def _como_array(datos):
    import numpy as np
    tipo, obj = datos
    if tipo == "bgra":
        return obj
    ancho, alto = obj.size
    return np.frombuffer(obj.bgra, dtype=np.uint8).reshape(alto, ancho, 4)


class CuadroDiferido(Image.Image):
    """Cuadro que se lee del disco solo cuando el codificador lo pide.

    Así crear el AVIF no necesita tener todos los cuadros en memoria a la vez.
    """

    def __init__(self, ruta, tam):
        super().__init__()
        self._mode = "RGB"
        self._size = tam
        self.ruta = ruta

    def seek(self, frame):
        if frame != 0:
            raise EOFError

    def tell(self):
        return 0

    def tobytes(self, encoder_name="raw", *args):
        with Image.open(self.ruta) as img:
            return img.convert("RGB").tobytes(encoder_name, *args)


def avif_disponible():
    try:
        return bool(features.check("avif"))
    except Exception:
        return False


def duraciones(n, fps):
    """Milisegundos por cuadro que suman exacto (60 fps -> 17, 17, 16, ...)."""
    return [round((i + 1) * 1000 / fps) - round(i * 1000 / fps) for i in range(n)]


EXTENSIONES_CUADRO = {".png", ".jpg", ".jpeg", ".webp"}


def cuadros_de(carpeta):
    """Cuadros que hay ahora en la carpeta de una animación, en orden (respeta los que se borren a mano)."""
    return sorted(p for p in Path(carpeta).iterdir() if p.suffix.lower() in EXTENSIONES_CUADRO)


def info_de(carpeta):
    """Lo que se anotó al grabar (info.json); {} si no existe."""
    try:
        return json.loads((Path(carpeta) / "info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def crear_avif(rutas, destino, fps, calidad=80, hilos=None):
    """Une los cuadros en un AVIF animado. Escribe a un temporal y luego renombra."""
    with Image.open(rutas[0]) as img:
        primero = img.convert("RGB")
    resto = [CuadroDiferido(r, primero.size) for r in rutas[1:]]
    opciones = dict(save_all=True, append_images=resto, duration=duraciones(len(rutas), fps),
                    loop=0, quality=calidad, speed=8)
    if hilos:
        opciones["max_threads"] = hilos
    temporal = destino.with_name(destino.name + ".tmp")
    primero.save(temporal, "AVIF", **opciones)
    temporal.replace(destino)


class GrabadorAnimacion:
    def __init__(self, config, avisar, pool):
        self.base = cap.carpeta_actual(config)  # la del temporizador seleccionado o la general
        self.sufijo = cap.limpiar_sufijo(config.get("sufijo"))
        self.ext = cap.extension(config.get("formato"))       # fijo para toda la animación
        self.resolucion = config.get("resolucion", "nativa")  # fija para toda la animación
        self.salida = config.get("anim_guardar", "ambos")     # "cuadros", "avif" o "ambos"
        self.fps = int(config.get("anim_fps", 60))
        limite_mb = config.get("anim_limite_mb")
        self.limite = int(limite_mb) * MB if limite_mb else limite_por_defecto()
        self.motor = config.get("motor", "auto")
        self.monitor = config.get("monitor", 1)
        self.config = config  # se lee "prioridad" en vivo
        self.avisar = avisar  # función(*evento)
        self._pool = pool     # procesos que comprimen

        self.carpeta = None
        self.numero = None
        self.total = 0
        self._parar = threading.Event()
        self._lock = threading.Lock()
        self._bytes = 0
        self._hechos = 0
        self._unicos = 0
        self._hilo = None
        self._entrada = queue.Queue()  # cuadros recién capturados (los toma _copiar)
        self._cola = queue.Queue()     # cuadros ya en memoria compartida esperando proceso
        self._banco = BancoMemoria()
        self._futuros = []
        self._errores_envio = []
        self._saturado = False  # la RAM pendiente llegó al límite: se repiten cuadros hasta bajar
        self._omitidos = 0      # cuadros que se repitieron por eso
        self._limitador = Limitador(self._procesos)
        # Mediciones para diagnosticar (se guardan en info.json de la animación).
        self._intervalos = []   # ms entre cuadros nuevos del juego
        self._costos = []       # ms que tardó tomar cada cuadro nuevo
        self._descartados = 0   # llegaron antes de 1/60 s (el juego va a más de 60 fps)
        self._absorbidos = 0    # detectados tarde y dejados en su lugar
        self.duracion_real = 0.0

    # ------------------------------------------------------------------ control

    def iniciar(self):
        self.carpeta, self.numero = nueva_carpeta(self.base, self.sufijo)
        self._hilo = threading.Thread(target=self._trabajar, daemon=True)
        self._hilo.start()

    def detener(self):
        self._parar.set()

    @property
    def grabando(self):
        return self._hilo is not None and self._hilo.is_alive() and not self._parar.is_set()

    def ocupado(self):
        """True mientras graba o todavía está guardando cuadros."""
        return self._hilo is not None and self._hilo.is_alive()

    def _modo(self):
        return self.config.get("prioridad", "juego")

    def _procesos(self):
        """Cuántos cuadros se comprimen a la vez, según la prioridad elegida. Nunca se suben
        solos: usar todos los núcleos le quitaba fluidez al juego. Si la memoria pendiente
        llega al límite, se repiten cuadros en vez de eso (ver _capturar)."""
        return HILOS.get(self._modo(), HILOS["juego"])

    # ------------------------------------------------------------------ nombres

    def _nombre(self):
        return f"{self.sufijo}-anim_{self.numero:03d}"

    def _ruta(self, indice, ancho=3):
        return self.carpeta / f"{self._nombre()}-{indice + 1:0{ancho}d}.{self.ext}"

    # ------------------------------------------------------------------ envío a los procesos

    def _despachar(self):
        """Hilo: manda cada cuadro a un proceso, respetando cuántos a la vez permite el modo."""
        opciones = dict(cap.opciones_imagen(self.config), resolucion=self.resolucion, rapido=True)
        while True:
            item = self._cola.get()
            if item is None:
                return
            indice, nombre, forma, tam = item
            self._limitador.tomar()
            try:
                futuro = self._pool.submit(trabajador.guardar, nombre, forma, str(self._ruta(indice)),
                                           opciones, self._modo())
            except Exception as e:  # el pool se cerró
                self._errores_envio.append(e)
                self._terminado(None, nombre, tam)
                continue
            futuro.add_done_callback(lambda f, nombre=nombre, tam=tam: self._terminado(f, nombre, tam))
            self._futuros.append(futuro)
            if len(self._futuros) > 512:  # grabaciones largas: no acumular los ya terminados
                self._futuros = [f for f in self._futuros if not f.done()]

    def _copiar(self):
        """Hilo: pasa cada cuadro a memoria compartida en cuanto llega.

        memmove de ctypes suelta el GIL mientras copia, así la captura no espera.
        """
        import numpy as np
        while True:
            item = self._entrada.get()
            if item is None:
                self._cola.put(None)
                return
            indice, arr = item
            arr = np.ascontiguousarray(arr)
            nombre, direccion = self._banco.obtener(arr.nbytes)
            ctypes.memmove(direccion, arr.ctypes.data, arr.nbytes)
            self._cola.put((indice, nombre, arr.shape, arr.nbytes))
            del arr, item

    def _terminado(self, futuro, nombre, tam):
        if futuro is not None and not futuro.cancelled() and futuro.exception() is not None:
            self._errores_envio.append(futuro.exception())
        self._banco.devolver(nombre)
        self._limitador.soltar()
        with self._lock:
            self._bytes -= tam
            self._hechos += 1

    # ------------------------------------------------------------------ mediciones

    def medidas(self):
        """Resumen para diagnosticar fluidez (lo que se ve en info.json y en Actividad)."""
        def mediana(v):
            v = sorted(v)
            return round(v[len(v) // 2], 1) if v else None

        def p95(v):
            v = sorted(v)
            return round(v[int(len(v) * 0.95)], 1) if v else None
        intervalo = mediana(self._intervalos)
        return {
            "fps_animacion": self.fps,
            "cuadros": self.total,
            "unicos": self._unicos,
            "repetidos": self.total - self._unicos,
            "duracion_real_s": round(self.duracion_real, 2),
            "duracion_animacion_s": round(self.total / self.fps, 2),
            "fps_del_juego": round(1000 / intervalo, 1) if intervalo else None,
            "descartados_por_llegar_antes": self._descartados,
            "detectados_tarde_absorbidos": self._absorbidos,
            "repetidos_por_memoria": self._omitidos,
            "captura_ms_mediana": mediana(self._costos),
            "captura_ms_p95": p95(self._costos),
            "monitor_hz": cap.frecuencia_monitor(),
            "resolucion": self.resolucion,
            "formato": self.ext,
            "prioridad": self._modo(),
        }

    # ------------------------------------------------------------------ trabajo

    def _trabajar(self):
        winmm = ctypes.windll.winmm if os.name == "nt" else None
        if winmm:
            winmm.timeBeginPeriod(1)  # sleep preciso (1 ms) mientras graba
        # Pasar el GIL entre hilos más seguido (por defecto cada 5 ms): la captura
        # recupera su turno enseguida aunque otro hilo de la app esté trabajando.
        intervalo_gil = sys.getswitchinterval()
        sys.setswitchinterval(0.0005)
        despachador = threading.Thread(target=self._despachar, daemon=True)
        copiador = threading.Thread(target=self._copiar, daemon=True)
        despachador.start()
        copiador.start()
        try:
            mapa, primero, motivo = self._capturar()
        finally:
            if winmm:
                winmm.timeEndPeriod(1)
            sys.setswitchinterval(intervalo_gil)
            self._entrada.put(None)

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
        medidas = self.medidas()
        if self.total:
            try:
                (self.carpeta / "info.json").write_text(json.dumps(medidas, indent=2), encoding="utf-8")
            except OSError:
                pass
        self.avisar("anim_fin", self.carpeta, miniatura, self.total, motivo, medidas)

        # Esperar a que los procesos terminen, avisando el avance.
        copiador.join()
        despachador.join()
        pendientes = set(self._futuros)
        while pendientes:
            _, pendientes = wait(pendientes, timeout=0.5)
            self.avisar("anim_guardando", self.carpeta, self._hechos, self._unicos)
        errores = list(self._errores_envio)
        self._banco.cerrar()

        # Cuadros repetidos: copiar el archivo del original (en el AVIF casi no pesan).
        if not errores:
            for i, origen in enumerate(mapa):
                if origen != i:
                    shutil.copyfile(self._ruta(origen), self._ruta(i))

        # Más de 999 cuadros: renombrar con más dígitos para que ordenen bien.
        ancho = max(3, len(str(self.total)))
        if ancho > 3 and not errores:
            for i in range(self.total):
                self._ruta(i).rename(self._ruta(i, ancho))

        final = self.carpeta
        if self.salida != "cuadros" and self.total and not errores:
            final, error_avif = self._hacer_avif(ancho)
            if error_avif:
                errores.append(error_avif)
        self.avisar("anim_guardada", self.carpeta, final, self.total, self.total / self.fps,
                    str(errores[0]) if errores else None)

    def _hacer_avif(self, ancho):
        """Crea el AVIF animado en un proceso aparte. Devuelve (ruta final, error o None)."""
        if not avif_disponible():
            return self.carpeta, "este Pillow no tiene AVIF (ejecuta instalar.bat); se dejaron los cuadros"
        # Solo AVIF: queda junto a las fotos. Ambos: dentro de la carpeta de cuadros.
        destino = (self.base if self.salida == "avif" else self.carpeta) / f"{self._nombre()}.avif"
        n = 2
        while destino.exists():  # nunca sobrescribir una animación anterior
            destino = destino.with_name(f"{self._nombre()}-{n}.avif")
            n += 1
        rutas = [str(self._ruta(i, ancho)) for i in range(self.total)]
        self.avisar("anim_avif", self.carpeta)
        try:
            self._pool.submit(trabajador.crear_avif, rutas, str(destino), self.fps,
                              HILOS.get(self._modo()), self._modo()).result()
        except Exception as e:
            return self.carpeta, f"no se pudo crear el AVIF ({e}); se dejaron los cuadros"
        if self.salida == "avif":
            shutil.rmtree(self.carpeta, ignore_errors=True)
        return destino, None

    # ------------------------------------------------------------------ captura

    def _capturar(self):
        """Devuelve (mapa, primer_cuadro, motivo). mapa[i] = índice del cuadro original."""
        try:
            capt = cap.Capturador(self.motor, self.monitor)  # propio de este hilo
        except Exception as e:
            return [], None, f"error: {e}"

        dt = 1.0 / self.fps
        mapa = []
        estado = {"ultimo": None, "primero": None}

        def emitir(datos):
            indice = len(mapa)
            if datos is None:  # repetir el cuadro anterior (no se copia, solo se anota)
                mapa.append(estado["ultimo"])
                return
            arr = _como_array(datos)  # sin copiar: dxcam ya entrega un arreglo nuevo por cuadro
            if estado["ultimo"] is not None:
                # La PC no alcanza a guardar: repetir el anterior hasta que se libere memoria.
                if self._saturado and self._bytes < self.limite * 0.6:
                    self._saturado = False
                elif not self._saturado and self._bytes + arr.nbytes > self.limite:
                    self._saturado = True
                    if not self._omitidos:
                        self.avisar("log", "[!] La PC no alcanza a guardar todos los cuadros: se repetirán "
                                           "algunos hasta que se ponga al día. La grabación sigue.")
                if self._saturado:
                    self._omitidos += 1
                    mapa.append(estado["ultimo"])
                    return
            with self._lock:
                self._bytes += arr.nbytes
                self._unicos += 1
            mapa.append(indice)
            estado["ultimo"] = indice
            if estado["primero"] is None:
                estado["primero"] = datos
            self._entrada.put((indice, arr))

        motivo = "detenida"
        try:
            cap.prioridad_hilo(self._modo(), captura=True)
            emitir(capt.tomar())
            t0 = t_ref = t_ant = time.perf_counter()
            ritmo = dt              # cada cuánto llegan cuadros del juego (promedio)
            proximo_aviso = t0
            por_eventos = getattr(capt, "_dxcam", None) is not None

            while not self._parar.is_set():
                if por_eventos:
                    antes = time.perf_counter()
                    datos = capt.fotograma()  # None si el juego no mostró un cuadro nuevo
                    ahora = time.perf_counter()
                    if datos is None:
                        # Pantalla quieta: ir repitiendo para que la duración sea la real.
                        k = round((ahora - t_ref) / dt)
                        if k >= 2:
                            for _ in range(k - 1):
                                emitir(None)
                            t_ref += (k - 1) * dt
                        time.sleep(0.001)
                    else:
                        self._costos.append((ahora - antes) * 1000)
                        self._intervalos.append((ahora - t_ant) * 1000)
                        k = round((ahora - t_ref) / dt)
                        parejo = 0.95 * dt < ritmo < 1.05 * dt  # ritmo de antes de este cuadro
                        ritmo = 0.9 * ritmo + 0.1 * (ahora - t_ant)
                        t_ant = ahora
                        if k == 2 and parejo:
                            # El juego va parejo a ~60: un cuadro que "llega" casi al doble
                            # casi siempre es uno detectado tarde, no uno perdido. Se deja en
                            # su lugar; si de verdad faltó uno, el siguiente lo corrige solo.
                            k = 1
                            self._absorbidos += 1
                        if k <= 0:
                            self._descartados += 1
                        if k >= 1:  # k == 0: llegó antes de tiempo (monitor a más de 60 Hz)
                            for _ in range(k - 1):
                                emitir(None)
                            emitir(datos)
                            esperado = t_ref + k * dt
                            # Seguir el ritmo real del juego si va a ~60 fps o menos;
                            # si va más rápido, mantener el ritmo fijo de 60.
                            t_ref = ahora if (abs(ahora - esperado) < TOLERANCIA and ritmo > 0.75 * dt) else esperado
                else:
                    # mss (sin dxcam): mirar la pantalla a horas fijas.
                    espera = t0 + len(mapa) * dt - time.perf_counter()
                    if espera > 0:
                        time.sleep(espera)
                    emitir(capt.fotograma())
                    atraso = int((time.perf_counter() - t0) / dt) - len(mapa)
                    for _ in range(max(0, atraso)):
                        emitir(None)
                    ahora = time.perf_counter()

                if ahora >= proximo_aviso:
                    proximo_aviso = ahora + AVISAR_CADA_SEG
                    self.avisar("anim_progreso", len(mapa), ahora - t0)
                    cap.prioridad_hilo(self._modo(), captura=True)  # sigue el modo si se cambia

            # Completar hasta el momento en que se detuvo.
            if por_eventos and mapa:
                k = round((time.perf_counter() - t_ref) / dt)
                for _ in range(max(0, k - 1)):
                    emitir(None)
            self.duracion_real = time.perf_counter() - t0
        except Exception as e:
            motivo = f"error: {e}"

        self._parar.set()
        return mapa, estado["primero"], motivo
