"""
Capturador de pantalla con mando (XInput) para jugar sin pausar el juego.

- Lee el mando directamente con XInput (no crea ventanas ni roba el foco,
  así que el juego no se pausa).
- Toma la captura con DXGI (dxcam) si está instalado, o con mss como respaldo.
- Guarda la imagen en un hilo aparte para no frenar la lectura del mando.

Uso:
    python capturador.py            -> menú interactivo
    python capturador.py iniciar    -> empieza a escuchar el mando
    python capturador.py agregar    -> añade un atajo (presionas el botón)
    python capturador.py listar     -> muestra los atajos
    python capturador.py borrar N   -> borra el atajo con nombre N
    python capturador.py probar     -> muestra en vivo los botones presionados
"""

import argparse
import copy
import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ¿Corre como .exe (PyInstaller)? Entonces los archivos del programa están en
# sys._MEIPASS (solo lectura) y los datos del usuario van a %APPDATA%\Capturador.
CONGELADO = getattr(sys, "frozen", False)
CARPETA_SCRIPT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # icono y demás recursos
if CONGELADO:
    CARPETA_DATOS = Path(os.environ.get("APPDATA", Path.home())) / "Capturador"
else:
    CARPETA_DATOS = CARPETA_SCRIPT  # desde el código: config y tiempos junto a los .py, como siempre
CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
# Identidad de la app en la barra de tareas (no cambiarla: el icono anclado depende de ella).
APP_ID = "CapturadorSilksong"
ARCHIVO_CONFIG = CARPETA_DATOS / "config.json"
ARCHIVOS_DE_DATOS = ("config.json", "tiempos.csv", "en_curso.json")


def migrar_datos():
    """Copia config y tiempos de una instalación anterior si aquí todavía no hay.

    - Desde el código: la carpeta se llamaba capturador_silksong.
    - Desde el .exe: también busca la instalación desde el código.
    Copia (no mueve) para no perder nada. Devuelve la carpeta de donde copió, o None.
    """
    if ARCHIVO_CONFIG.exists():
        return None
    candidatos = [CARPETA_SCRIPT.parent / "capturador_silksong"]
    if CONGELADO:
        base = Path.home() / "test001"
        candidatos = [base / "capturador", base / "capturador_silksong"]
    import shutil
    for viejo in candidatos:
        if (viejo / "config.json").exists():
            for nombre in ARCHIVOS_DE_DATOS:
                if (viejo / nombre).exists() and not (CARPETA_DATOS / nombre).exists():
                    shutil.copy2(viejo / nombre, CARPETA_DATOS / nombre)
            return viejo
    return None

CONFIG_POR_DEFECTO = {
    "carpeta": str(Path.home() / "Pictures" / "Silksong"),
    "sufijo": "captura",       # fotos: captura-001.png; animaciones: anim01/captura-anim01-001.png
    "formato": "webp",         # "png", "jpg" o "webp" (webp: ~10 % de un png con la misma calidad visible)
    "resolucion": "720p",      # "nativa" o "720p" (se reduce después de capturar)
    "prioridad": "juego",      # "juego" (no frenar el juego) o "grabacion" (guardar rápido)
    "calidad_jpg": 95,
    "calidad_webp": 90,        # 90 se ve igual que el original y pesa ~10 % de un PNG
    "motor": "auto",           # "auto", "dxcam" o "mss"
    "monitor": 1,              # 1 = monitor principal
    "sonido": False,          # aviso de Windows al tomar cada foto
    "espera_entre_fotos": 0.3, # segundos mínimos entre dos fotos del mismo atajo
    "atajos": [],              # [{"nombre": "foto", "botones": ["BACK", "RB"]}]
    "timers": [],              # [{"nombre": "escribir"}]; se inician/paran con "atajo_timer"
}

# --------------------------------------------------------------------------
# Botones
# --------------------------------------------------------------------------

BOTONES = {
    "DPAD_ARRIBA": 0x0001,
    "DPAD_ABAJO": 0x0002,
    "DPAD_IZQ": 0x0004,
    "DPAD_DER": 0x0008,
    "START": 0x0010,
    "BACK": 0x0020,
    "LS": 0x0040,       # clic stick izquierdo
    "RS": 0x0080,       # clic stick derecho
    "LB": 0x0100,
    "RB": 0x0200,
    "GUIA": 0x0400,     # solo si XInputGetStateEx está disponible
    "A": 0x1000,
    "B": 0x2000,
    "X": 0x4000,
    "Y": 0x8000,
    # Gatillos convertidos en botones virtuales
    "LT": 0x10000,
    "RT": 0x20000,
}
UMBRAL_GATILLO = 128


# Teclas del teclado: se guardan como "VK:0x78" (código de tecla de Windows) y
# ocupan bits por encima de los del mando (1 << (BIT_TECLADO + código)).
BIT_TECLADO = 32
VK_ESC = 0x1B
_MODIFICADORES = {0x11: "Ctrl", 0x10: "Shift", 0x12: "Alt"}
_NOMBRES_TECLAS = {
    0x08: "Retroceso", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pausa", 0x14: "BloqMayús", 0x1B: "Esc",
    0x20: "Espacio", 0x21: "RePág", 0x22: "AvPág", 0x23: "Fin", 0x24: "Inicio", 0x25: "←", 0x26: "↑",
    0x27: "→", 0x28: "↓", 0x2C: "ImprPant", 0x2D: "Insert", 0x2E: "Supr", 0x6A: "Num *", 0x6B: "Num +",
    0x6D: "Num −", 0x6E: "Num .", 0x6F: "Num /", 0x90: "BloqNum", 0x91: "BloqDespl",
}
# Teclas que se revisan al asignar: todas menos botones del mouse, Ctrl/Shift/Alt izquierdo
# y derecho (se usan los genéricos) y las teclas de Windows.
_TECLAS_ASIGNABLES = [vk for vk in range(0x08, 0xFF)
                      if vk not in (0x5B, 0x5C, 0x5D) and not 0xA0 <= vk <= 0xA5 and vk not in (0x0A, 0x0B, 0x0E, 0x0F)]


def nombre_tecla(vk):
    if vk in _MODIFICADORES:
        return _MODIFICADORES[vk]
    if vk in _NOMBRES_TECLAS:
        return _NOMBRES_TECLAS[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"Num {vk - 0x60}"
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if os.name == "nt":  # teclas de símbolos: pedirle el nombre a Windows (depende del idioma)
        try:
            u32 = ctypes.windll.user32
            buf = ctypes.create_unicode_buffer(32)
            if u32.GetKeyNameTextW(u32.MapVirtualKeyW(vk, 0) << 16, buf, 32):
                return buf.value
        except Exception:
            pass
    return f"Tecla {vk:#04x}"


def es_tecla(nombre):
    return nombre.startswith("VK:")


def _vk(nombre):
    return int(nombre[3:], 16)


def mascara_a_nombres(mascara):
    nombres = [n for n, bit in BOTONES.items() if mascara & bit]
    teclas = [vk for vk in range(256) if mascara >> (BIT_TECLADO + vk) & 1]
    # Ctrl / Shift / Alt primero, como se escriben normalmente (Ctrl + Shift + S).
    teclas.sort(key=lambda vk: (vk not in _MODIFICADORES, list(_MODIFICADORES).index(vk) if vk in _MODIFICADORES else vk))
    return nombres + [f"VK:{vk:#04x}" for vk in teclas]


def nombres_a_mascara(nombres):
    mascara = 0
    for n in nombres:
        if es_tecla(n):
            mascara |= 1 << (BIT_TECLADO + _vk(n))
        elif n in BOTONES:
            mascara |= BOTONES[n]
        else:
            raise ValueError(f"Botón desconocido en config.json: {n}")
    return mascara


def teclas_de(nombres):
    """Códigos de tecla que usa una combinación."""
    return {_vk(n) for n in nombres if es_tecla(n)}


def texto_combo(nombres):
    return " + ".join(nombre_tecla(_vk(n)) if es_tecla(n) else n for n in nombres)


class Teclado:
    """Lee el teclado aunque el juego tenga el foco (GetAsyncKeyState)."""

    def __init__(self):
        self._u32 = ctypes.windll.user32 if os.name == "nt" else None

    def _presionadas(self, vks):
        if self._u32 is None:
            return []
        leer = self._u32.GetAsyncKeyState
        return [vk for vk in vks if leer(vk) & 0x8000]

    def leer(self, vks):
        """Máscara con las teclas indicadas que están presionadas (solo se revisan esas)."""
        mascara = 0
        for vk in self._presionadas(vks):
            mascara |= 1 << (BIT_TECLADO + vk)
        return mascara

    def leer_para_asignar(self):
        """(máscara de todas las teclas asignables presionadas, ¿Esc presionado?)."""
        presionadas = self._presionadas(_TECLAS_ASIGNABLES)
        esc = VK_ESC in presionadas
        mascara = 0
        for vk in presionadas:
            if vk != VK_ESC:
                mascara |= 1 << (BIT_TECLADO + vk)
        return mascara, esc


# --------------------------------------------------------------------------
# XInput
# --------------------------------------------------------------------------

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", XINPUT_GAMEPAD)]


ERROR_SUCCESS = 0
REVISAR_DESCONECTADOS_CADA = 2.0  # XInput es lento con mandos desconectados


class XInput:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("XInput solo está disponible en Windows.")
        dll = None
        for nombre in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                dll = ctypes.WinDLL(nombre)
                break
            except OSError:
                continue
        if dll is None:
            raise RuntimeError("No se encontró ninguna DLL de XInput.")

        # XInputGetStateEx (ordinal 100) también reporta el botón Guía.
        try:
            self._get_state = dll[100]
        except (AttributeError, OSError):
            self._get_state = dll.XInputGetState
        self._get_state.argtypes = [ctypes.c_ulong, ctypes.POINTER(XINPUT_STATE)]
        self._get_state.restype = ctypes.c_ulong

        self._estado = XINPUT_STATE()
        self._conectados = [True] * 4
        self._ultimo_chequeo = [0.0] * 4

    def leer(self, ahora=None):
        """Devuelve la máscara combinada de los 4 mandos posibles."""
        ahora = time.monotonic() if ahora is None else ahora
        mascara = 0
        for i in range(4):
            if not self._conectados[i] and ahora - self._ultimo_chequeo[i] < REVISAR_DESCONECTADOS_CADA:
                continue
            self._ultimo_chequeo[i] = ahora
            if self._get_state(i, ctypes.byref(self._estado)) != ERROR_SUCCESS:
                self._conectados[i] = False
                continue
            self._conectados[i] = True
            pad = self._estado.Gamepad
            mascara |= pad.wButtons
            if pad.bLeftTrigger > UMBRAL_GATILLO:
                mascara |= BOTONES["LT"]
            if pad.bRightTrigger > UMBRAL_GATILLO:
                mascara |= BOTONES["RT"]
        return mascara

    def alguno_conectado(self):
        return any(self._conectados)

    def hay_mando(self):
        self._ultimo_chequeo = [0.0] * 4  # fuerza revisar los 4
        self._conectados = [True] * 4
        self.leer()
        return any(self._conectados)


# --------------------------------------------------------------------------
# Detección de atajos (independiente de Windows, para poder probarla)
# --------------------------------------------------------------------------

class DetectorAtajos:
    """Dispara un atajo cuando su combinación se completa (flanco de subida).

    Si varios atajos se completan a la vez gana el de más botones, para que
    BACK+RB no dispare también un atajo que sea solo BACK.
    """

    def __init__(self, atajos, espera):
        self.atajos = sorted(
            ((a["nombre"], nombres_a_mascara(a["botones"])) for a in atajos),
            key=lambda x: bin(x[1]).count("1"),
            reverse=True,
        )
        self.espera = espera
        self._anterior = 0
        self._ultimo_disparo = {}

    def actualizar(self, mascara, ahora):
        disparado = None
        for nombre, combo in self.atajos:
            completo_ahora = (mascara & combo) == combo
            completo_antes = (self._anterior & combo) == combo
            if completo_ahora and not completo_antes:
                if ahora - self._ultimo_disparo.get(nombre, -1e9) >= self.espera:
                    self._ultimo_disparo[nombre] = ahora
                    disparado = nombre
                break  # solo el combo más grande que se completó
        self._anterior = mascara
        return disparado


# --------------------------------------------------------------------------
# Captura de pantalla
# --------------------------------------------------------------------------

class Capturador:
    """Toma el fotograma (rápido) en el hilo del mando; devuelve una PIL.Image."""

    def __init__(self, motor="auto", monitor=1):
        self.monitor = monitor
        self._dxcam = None
        self._mss = None
        self.nombre_motor = None

        if motor in ("auto", "dxcam"):
            try:
                import dxcam
                self._dxcam = dxcam.create(
                    output_idx=max(monitor - 1, 0),
                    # BGRA es el formato nativo: así dxcam no necesita OpenCV (cv2).
                    output_color="BGRA",
                )
                if self._dxcam is None:
                    raise RuntimeError("dxcam no pudo abrir el monitor")
                self.nombre_motor = "dxcam (DXGI)"
            except Exception as e:
                if motor == "dxcam":
                    raise
                print(f"  dxcam no disponible ({e}); se usará mss.")
                self._dxcam = None

        if self._dxcam is None:
            import mss
            self._mss = mss.mss()
            self.nombre_motor = "mss (GDI)"

    def tomar(self):
        """Devuelve un objeto ligero; la conversión pesada se hace en otro hilo."""
        if self._dxcam is not None:
            try:
                # grab() devuelve None si no hubo fotograma nuevo; reintenta un poco.
                for _ in range(10):
                    frame = self._dxcam.grab()
                    if frame is not None:
                        return ("bgra", frame)
                    time.sleep(0.005)
            except Exception as e:
                print(f"  dxcam falló ({e}); se usará mss desde ahora.")
                self._dxcam = None
                self.nombre_motor = "mss (GDI)"
            # Pantalla estática o dxcam falló: usamos mss.
            if self._mss is None:
                import mss
                self._mss = mss.mss()
        shot = self._mss.grab(self._mss.monitors[self.monitor])
        return ("mss", shot)

    def fotograma(self):
        """Para animaciones: un fotograma sin reintentos, o None si la pantalla no cambió."""
        if self._dxcam is not None:
            frame = self._dxcam.grab()
            return None if frame is None else ("bgra", frame)
        return ("mss", self._mss.grab(self._mss.monitors[self.monitor]))

    @staticmethod
    def a_imagen(datos):
        import numpy as np
        from PIL import Image
        tipo, obj = datos
        if tipo == "bgra":
            alto, ancho = obj.shape[:2]
            # frombuffer evita copiar los 8 MB del fotograma antes de convertir.
            return Image.frombuffer("RGB", (ancho, alto), np.ascontiguousarray(obj), "raw", "BGRX", 0, 1)
        return Image.frombytes("RGB", obj.size, obj.bgra, "raw", "BGRX")


AUTOSHOT = "autoshot"  # nombre de las fotos automáticas


class Guardador(threading.Thread):
    """Codifica y guarda en segundo plano para no bloquear la lectura del mando."""

    def __init__(self, config, aviso=print, al_guardar=None, pool=None):
        super().__init__(daemon=True)
        self.config = config
        self.aviso = aviso            # función que recibe el texto a mostrar
        self.al_guardar = al_guardar  # opcional: función(ruta, imagen) tras guardar
        self.pool = pool              # opcional: procesos donde comprimir (no frenan la captura)
        self.cola = queue.Queue()
        self.carpeta = carpeta_actual(config)

    def run(self):
        while True:
            item = self.cola.get()
            if item is None:
                break
            nombre_atajo, momento, datos = item[:3]
            reserva = item[3] if len(item) > 3 else None  # (carpeta, sufijo, número) ya apartado
            try:
                ruta, img = self._guardar(nombre_atajo, momento, datos, reserva)
                if nombre_atajo == AUTOSHOT:
                    continue  # las automáticas se guardan en silencio (pueden ser cientos)
                self.aviso(f"  [foto] [{nombre_atajo}] {ruta.name}")
                if self.al_guardar:
                    self.al_guardar(ruta, img)
                if self.config["sonido"]:
                    sonar()
            except Exception as e:
                self.aviso(f"  [!] Error al guardar: {e}")
            finally:
                self.cola.task_done()

    def _guardar(self, nombre_atajo, momento, datos, reserva=None):
        modo = self.config.get("prioridad", "juego")
        ext = extension(self.config["formato"])
        if reserva is None:
            # Se lee cada vez por si la carpeta o el sufijo se cambiaron desde la app.
            carpeta = carpeta_actual(self.config)
            sufijo = limpiar_sufijo(self.config.get("sufijo"))
            reserva = (carpeta, sufijo, reservar_numero(carpeta, sufijo))
        carpeta, sufijo, numero = reserva
        carpeta.mkdir(parents=True, exist_ok=True)
        self.carpeta = carpeta
        ruta = carpeta / f"{sufijo}-{numero:03d}.{ext}"

        if self.pool is None:
            prioridad_hilo(modo)
            img = ajustar_resolucion(Capturador.a_imagen(datos), self.config.get("resolucion"))
            guardar_imagen(img, ruta, self.config)
            return ruta, img

        import trabajador
        from PIL import Image
        shm, forma = copiar_a_memoria(datos)
        try:
            tam, crudo = self.pool.submit(trabajador.guardar, shm.name, forma, str(ruta),
                                          opciones_imagen(self.config), modo, (528, 296)).result()
        finally:
            liberar_memoria(shm)
        return ruta, Image.frombytes("RGB", tam, crudo)


CARACTERES_PROHIBIDOS = re.compile(r'[\\/:*?"<>|]')


def limpiar_sufijo(sufijo):
    """Quita caracteres que Windows no acepta en nombres de archivo."""
    limpio = CARACTERES_PROHIBIDOS.sub("", str(sufijo or "")).strip().strip(".")
    return limpio or "captura"


def carpeta_actual(config):
    """Dónde guardar ahora: la carpeta del temporizador seleccionado si tiene una propia,
    si no, la carpeta general."""
    seleccionado = config.get("timer_seleccionado")
    for t in config.get("timers", []):
        if t["nombre"] == seleccionado and t.get("carpeta"):
            return Path(t["carpeta"]).expanduser()
    return Path(config["carpeta"]).expanduser()


def extension(formato):
    """'png', 'jpg' o 'webp' según el formato elegido."""
    formato = str(formato or "png").lower()
    return {"jpeg": "jpg", "jpg": "jpg", "webp": "webp"}.get(formato, "png")


def guardar_imagen(img, ruta, config, rapido=False):
    """Guarda según la extensión de la ruta. rapido=True para cuadros de animación."""
    ext = ruta.suffix.lower().lstrip(".")
    if ext == "jpg":
        img.save(ruta, "JPEG", quality=int(config.get("calidad_jpg", 95)))
    elif ext == "webp":
        # method 2 pesa casi lo mismo que 4 y tarda la mitad.
        img.save(ruta, "WEBP", quality=int(config.get("calidad_webp", 90)), method=2 if rapido else 4)
    else:
        # compress_level bajo = mucho más rápido, archivo algo más grande.
        img.save(ruta, "PNG", compress_level=1)


def siguiente_numero(carpeta, sufijo):
    """Siguiente número libre del sufijo. Fotos y animaciones comparten la cuenta:

    doric-001.webp, doric-002.webp, doric-anim_003/ (o doric-anim_003.avif), doric-004.webp…
    """
    patron = re.compile(re.escape(sufijo) + r"-(?:anim_)?(\d+)(?:\.(?:png|jpe?g|webp|avif))?$", re.IGNORECASE)
    carpeta = Path(carpeta)
    if not carpeta.exists():
        return 1
    numeros = [int(m.group(1)) for p in carpeta.iterdir() if (m := patron.match(p.name))]
    return max(numeros, default=0) + 1


_reservas = {}
_reservas_lock = threading.Lock()


def reservar_numero(carpeta, sufijo):
    """Aparta el siguiente número para que una foto y una animación nunca tomen el mismo,
    aunque el archivo todavía no exista en el disco."""
    with _reservas_lock:
        clave = (str(Path(carpeta).expanduser()).lower(), sufijo.lower())
        numero = max(siguiente_numero(carpeta, sufijo), _reservas.get(clave, 0) + 1)
        _reservas[clave] = numero
        return numero


def opciones_imagen(config):
    """Lo que un proceso trabajador necesita saber para guardar (solo datos simples)."""
    return {"resolucion": config.get("resolucion", "nativa"),
            "calidad_jpg": config.get("calidad_jpg", 95),
            "calidad_webp": config.get("calidad_webp", 90)}


def copiar_a_memoria(datos):
    """Copia un cuadro (dxcam o mss) a memoria compartida. Devuelve (shm, forma)."""
    import numpy as np
    from multiprocessing import shared_memory
    tipo, obj = datos
    if tipo == "bgra":
        arr = obj
    else:
        ancho, alto = obj.size
        arr = np.frombuffer(obj.bgra, dtype=np.uint8).reshape(alto, ancho, 4)
    shm = shared_memory.SharedMemory(create=True, size=arr.nbytes)
    destino = np.ndarray(arr.shape, dtype=np.uint8, buffer=shm.buf)
    destino[:] = arr
    del destino
    return shm, arr.shape


def liberar_memoria(shm):
    shm.close()
    try:
        shm.unlink()  # en Windows no hace falta (se libera al cerrar), en Linux sí
    except FileNotFoundError:
        pass


def sonar():
    """El aviso de Windows (SystemAsterisk), al volumen elegido en la app."""
    if os.name != "nt":
        return
    try:
        import sonidos
        sonidos.reproducir("aviso")
    except Exception:
        import winsound
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)


# Prioridades de Windows según el modo de rendimiento.
_PRIORIDAD_PROCESO = {"juego": 0x00004000, "grabacion": 0x00000020}  # BELOW_NORMAL / NORMAL
_PRIORIDAD_TRABAJO = {"juego": -2, "grabacion": 0}   # hilos que guardan: LOWEST / NORMAL
# El hilo que captura trabaja muy poco por cuadro, así que puede ir con prioridad alta
# sin quitarle fluidez al juego, y así no pierde cuadros.
_PRIORIDAD_CAPTURA = {"juego": 2, "grabacion": 15}   # hilo que captura: HIGHEST / TIME_CRITICAL


def frecuencia_monitor():
    """Hz del monitor principal (None si no se puede saber)."""
    if os.name != "nt":
        return None
    try:
        class DEVMODEW(ctypes.Structure):
            _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_ushort),
                        ("dmDriverVersion", ctypes.c_ushort), ("dmSize", ctypes.c_ushort),
                        ("dmDriverExtra", ctypes.c_ushort), ("dmFields", ctypes.c_ulong),
                        ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
                        ("dmDisplayOrientation", ctypes.c_ulong), ("dmDisplayFixedOutput", ctypes.c_ulong),
                        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                        ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                        ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                        ("dmLogPixels", ctypes.c_ushort), ("dmBitsPerPel", ctypes.c_ulong),
                        ("dmPelsWidth", ctypes.c_ulong), ("dmPelsHeight", ctypes.c_ulong),
                        ("dmDisplayFlags", ctypes.c_ulong), ("dmDisplayFrequency", ctypes.c_ulong),
                        ("dmICMMethod", ctypes.c_ulong), ("dmICMIntent", ctypes.c_ulong),
                        ("dmMediaType", ctypes.c_ulong), ("dmDitherType", ctypes.c_ulong),
                        ("dmReserved1", ctypes.c_ulong), ("dmReserved2", ctypes.c_ulong),
                        ("dmPanningWidth", ctypes.c_ulong), ("dmPanningHeight", ctypes.c_ulong)]
        modo = DEVMODEW()
        modo.dmSize = ctypes.sizeof(DEVMODEW)
        if ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(modo)):  # ENUM_CURRENT_SETTINGS
            return int(modo.dmDisplayFrequency) or None
    except Exception:
        pass
    return None


def aplicar_prioridad(modo):
    """Prioridad de todo el proceso: por debajo de lo normal en modo juego."""
    if os.name == "nt":
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), _PRIORIDAD_PROCESO.get(modo, 0x00004000))


def prioridad_hilo(modo, captura=False):
    """Prioridad del hilo actual (se llama en cada tarea, así el cambio de modo aplica al momento)."""
    if os.name == "nt":
        tabla = _PRIORIDAD_CAPTURA if captura else _PRIORIDAD_TRABAJO
        k32 = ctypes.windll.kernel32
        k32.SetThreadPriority(k32.GetCurrentThread(), tabla.get(modo, 0))


def bajar_prioridad():
    aplicar_prioridad("juego")


def ajustar_resolucion(img, resolucion):
    """Reduce a 720 px de alto si se pidió 720p (mantiene la proporción de la pantalla)."""
    if resolucion != "720p" or img.height <= 720:
        return img
    from PIL import Image
    ancho = round(img.width * 720 / img.height)
    return img.resize((ancho, 720), Image.LANCZOS)


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

def cargar_config():
    config = copy.deepcopy(CONFIG_POR_DEFECTO)
    if ARCHIVO_CONFIG.exists():
        with open(ARCHIVO_CONFIG, encoding="utf-8") as f:
            config.update(json.load(f))
    return config


def guardar_config(config):
    with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

INTERVALO_LECTURA = 1 / 120


def esperar_combo(xi):
    """Espera a que se suelte todo, luego registra lo que se presione hasta soltar."""
    while xi.leer():
        time.sleep(INTERVALO_LECTURA)
    acumulado = 0
    while True:
        m = xi.leer()
        if m:
            acumulado |= m
        elif acumulado:
            return acumulado
        time.sleep(INTERVALO_LECTURA)


def cmd_agregar(config):
    xi = XInput()
    if not xi.hay_mando():
        print("No se detecta ningún mando XInput. Conéctalo e intenta de nuevo.")
        return
    print("\nPresiona el botón (o mantén una combinación) con el que tomaremos fotos.")
    print("Al soltar todo, se guardará.")
    mascara = esperar_combo(xi)
    nombres = mascara_a_nombres(mascara)
    print(f"  Detectado: {texto_combo(nombres)}")

    otros = [{"nombre": "atajo de temporizador", "botones": config["atajo_timer"]}] if config.get("atajo_timer") else []
    for a in config["atajos"] + otros:
        if nombres_a_mascara(a["botones"]) == mascara:
            print(f"  Esa combinación ya está asignada a '{a['nombre']}'.")
            return

    if len(nombres) == 1:
        print("  Ojo: un solo botón también lo usa el juego. Una combinación")
        print("  como BACK + RB evita disparos accidentales.")

    sugerido = f"foto{len(config['atajos']) + 1}"
    nombre = input(f"Nombre para este atajo [{sugerido}]: ").strip() or sugerido
    if any(a["nombre"] == nombre for a in config["atajos"]):
        print(f"  Ya existe un atajo llamado '{nombre}'.")
        return
    config["atajos"].append({"nombre": nombre, "botones": nombres})
    guardar_config(config)
    print(f"  [ok] Atajo '{nombre}' = {texto_combo(nombres)}")


def cmd_listar(config):
    if not config["atajos"]:
        print("No hay atajos todavía.")
        return
    print("\nAtajos:")
    for a in config["atajos"]:
        print(f"  - {a['nombre']}: {texto_combo(a['botones'])}")


def cmd_borrar(config, nombre):
    antes = len(config["atajos"])
    config["atajos"] = [a for a in config["atajos"] if a["nombre"] != nombre]
    if len(config["atajos"]) == antes:
        print(f"No existe el atajo '{nombre}'.")
        return
    guardar_config(config)
    print(f"[ok] Atajo '{nombre}' borrado.")


def cmd_probar():
    xi = XInput()
    print("Presiona botones (Ctrl+C para salir)...")
    anterior = None
    try:
        while True:
            m = xi.leer()
            if m != anterior:
                print("  " + (texto_combo(mascara_a_nombres(m)) or "(nada)"))
                anterior = m
            time.sleep(INTERVALO_LECTURA)
    except KeyboardInterrupt:
        pass


def cmd_iniciar(config):
    if not config["atajos"]:
        print("Primero agrega un atajo.")
        return

    bajar_prioridad()
    xi = XInput()
    capturador = Capturador(config["motor"], config["monitor"])
    guardador = Guardador(config)
    guardador.start()
    detector = DetectorAtajos(config["atajos"], config["espera_entre_fotos"])

    print(f"\nMotor de captura: {capturador.nombre_motor}")
    print(f"Guardando en: {guardador.carpeta}")
    cmd_listar(config)
    print("\nListo. Ahora haz clic en el juego para que tenga el foco.")
    print("Deja esta ventana abierta (Ctrl+C aquí para salir).\n")

    try:
        while True:
            ahora = time.monotonic()
            nombre = detector.actualizar(xi.leer(ahora), ahora)
            if nombre:
                momento = datetime.now()
                try:
                    datos = capturador.tomar()  # solo copia el fotograma (rápido)
                    guardador.cola.put((nombre, momento, datos))
                except Exception as e:
                    print(f"  [!] No se pudo tomar la foto: {e}")
            time.sleep(INTERVALO_LECTURA)
    except KeyboardInterrupt:
        print("\nTerminando, guardando fotos pendientes...")
        guardador.cola.join()


def cmd_sonido(config):
    config["sonido"] = not config["sonido"]
    guardar_config(config)
    print(f"[ok] Sonido al tomar foto: {'activado' if config['sonido'] else 'desactivado'}")


def menu(config):
    opciones = {
        "1": ("Iniciar (escuchar el mando)", lambda: cmd_iniciar(config)),
        "2": ("Agregar atajo", lambda: cmd_agregar(config)),
        "3": ("Ver atajos", lambda: cmd_listar(config)),
        "4": ("Borrar atajo", lambda: cmd_borrar(config, input("Nombre a borrar: ").strip())),
        "5": ("Probar mando", cmd_probar),
        "6": (None, lambda: cmd_sonido(config)),
        "0": ("Salir", None),
    }
    while True:
        print("\n=== Capturador ===")
        for k, (texto, _) in opciones.items():
            if k == "6":
                texto = f"Sonido al tomar foto: {'SI' if config['sonido'] else 'NO'} (cambiar)"
            print(f"  {k}) {texto}")
        eleccion = input("> ").strip()
        if eleccion == "0":
            return
        if eleccion in opciones:
            try:
                opciones[eleccion][1]()
            except Exception as e:
                print(f"[!] {e}")


def main():
    p = argparse.ArgumentParser(description="Capturas de pantalla con el mando.")
    sub = p.add_subparsers(dest="comando")
    sub.add_parser("iniciar")
    sub.add_parser("agregar")
    sub.add_parser("listar")
    sub.add_parser("probar")
    b = sub.add_parser("borrar")
    b.add_argument("nombre")
    args = p.parse_args()

    config = cargar_config()
    if args.comando == "iniciar":
        cmd_iniciar(config)
    elif args.comando == "agregar":
        cmd_agregar(config)
    elif args.comando == "listar":
        cmd_listar(config)
    elif args.comando == "borrar":
        cmd_borrar(config, args.nombre)
    elif args.comando == "probar":
        cmd_probar()
    else:
        menu(config)


if __name__ == "__main__":
    main()
