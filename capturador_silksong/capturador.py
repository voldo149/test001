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
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

CARPETA_SCRIPT = Path(__file__).resolve().parent
ARCHIVO_CONFIG = CARPETA_SCRIPT / "config.json"

CONFIG_POR_DEFECTO = {
    "carpeta": str(Path.home() / "Pictures" / "Silksong"),
    "formato": "png",          # "png" o "jpg"
    "calidad_jpg": 95,
    "motor": "auto",           # "auto", "dxcam" o "mss"
    "monitor": 1,              # 1 = monitor principal
    "sonido": False,          # aviso de Windows al tomar cada foto
    "espera_entre_fotos": 0.3, # segundos mínimos entre dos fotos del mismo atajo
    "atajos": [],              # [{"nombre": "foto", "botones": ["BACK", "RB"]}]
    "timers": [],              # [{"nombre": "escribir", "botones": ["BACK", "Y"]}] (botones opcional)
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


def mascara_a_nombres(mascara):
    return [n for n, bit in BOTONES.items() if mascara & bit]


def nombres_a_mascara(nombres):
    mascara = 0
    for n in nombres:
        if n not in BOTONES:
            raise ValueError(f"Botón desconocido en config.json: {n}")
        mascara |= BOTONES[n]
    return mascara


def texto_combo(nombres):
    return " + ".join(nombres)


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

    @staticmethod
    def a_imagen(datos):
        from PIL import Image
        tipo, obj = datos
        if tipo == "bgra":
            alto, ancho = obj.shape[:2]
            return Image.frombytes("RGB", (ancho, alto), obj.tobytes(), "raw", "BGRX")
        return Image.frombytes("RGB", obj.size, obj.bgra, "raw", "BGRX")


class Guardador(threading.Thread):
    """Codifica y guarda en segundo plano para no bloquear la lectura del mando."""

    def __init__(self, config, aviso=print, al_guardar=None):
        super().__init__(daemon=True)
        self.config = config
        self.aviso = aviso            # función que recibe el texto a mostrar
        self.al_guardar = al_guardar  # opcional: función(ruta, imagen) tras guardar
        self.cola = queue.Queue()
        self.carpeta = Path(config["carpeta"]).expanduser()
        self.carpeta.mkdir(parents=True, exist_ok=True)

    def run(self):
        while True:
            item = self.cola.get()
            if item is None:
                break
            nombre_atajo, momento, datos = item
            try:
                ruta, img = self._guardar(nombre_atajo, momento, datos)
                self.aviso(f"  [foto] [{nombre_atajo}] {ruta.name}")
                if self.al_guardar:
                    self.al_guardar(ruta, img)
                if self.config["sonido"]:
                    sonar()
            except Exception as e:
                self.aviso(f"  [!] Error al guardar: {e}")
            finally:
                self.cola.task_done()

    def _guardar(self, nombre_atajo, momento, datos):
        img = Capturador.a_imagen(datos)
        fmt = self.config["formato"].lower()
        ext = "jpg" if fmt in ("jpg", "jpeg") else "png"
        sello = momento.strftime("%Y-%m-%d_%H-%M-%S_") + f"{momento.microsecond // 1000:03d}"
        seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in nombre_atajo)
        # Se lee cada vez por si la carpeta se cambió desde la app.
        self.carpeta = Path(self.config["carpeta"]).expanduser()
        self.carpeta.mkdir(parents=True, exist_ok=True)
        ruta = self.carpeta / f"silksong_{sello}_{seguro}.{ext}"
        if ext == "jpg":
            img.save(ruta, "JPEG", quality=int(self.config["calidad_jpg"]))
        else:
            # compress_level bajo = mucho más rápido, archivo algo más grande.
            img.save(ruta, "PNG", compress_level=1)
        return ruta, img


def sonar():
    if os.name == "nt":
        import winsound
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)


def bajar_prioridad():
    """Prioridad 'por debajo de lo normal' para no quitarle CPU al juego."""
    if os.name == "nt":
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)


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

    for a in config["atajos"] + [t for t in config["timers"] if t.get("botones")]:
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
        print("\n=== Capturador Silksong ===")
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
