"""
Sonidos de la app con volumen propio (5 niveles).

winsound.Beep y los sonidos del sistema siempre suenan al volumen de
Windows, así que aquí se generan los WAV en memoria con el volumen ya
aplicado y se reproducen en un hilo (sin frenar nada).
"""

import io
import math
import os
import threading
import wave
from pathlib import Path

import numpy as np

MUESTREO = 44100
# Niveles 1-5. El oído percibe el volumen de forma logarítmica: con estos pasos
# cada nivel se nota parecido al anterior.
GANANCIAS = {1: 0.06, 2: 0.14, 3: 0.28, 4: 0.52, 5: 1.0}
volumen = 3

_cache = {}
_lock = threading.Lock()


def _wav(muestras, canales=1, muestreo=MUESTREO):
    """Arreglo float (-1..1) -> bytes WAV de 16 bits."""
    datos = (np.clip(muestras, -1, 1) * 32767).astype("<i2").tobytes()
    salida = io.BytesIO()
    with wave.open(salida, "wb") as w:
        w.setnchannels(canales)
        w.setsampwidth(2)
        w.setframerate(muestreo)
        w.writeframes(datos)
    return salida.getvalue()


def _tonos(notas, ganancia):
    """notas: [(frecuencia Hz, milisegundos)] -> WAV con entradas y salidas suaves (sin chasquidos)."""
    partes = []
    for frecuencia, ms in notas:
        n = int(MUESTREO * ms / 1000)
        t = np.arange(n) / MUESTREO
        onda = np.sin(2 * math.pi * frecuencia * t) * 0.6
        rampa = min(n // 4, int(MUESTREO * 0.006))
        envolvente = np.ones(n)
        envolvente[:rampa] = np.linspace(0, 1, rampa)
        envolvente[-rampa:] = np.linspace(1, 0, rampa)
        partes.append(onda * envolvente)
        partes.append(np.zeros(int(MUESTREO * 0.012)))  # pausa breve entre notas
    return _wav(np.concatenate(partes) * ganancia)


def _ruta_sonido_sistema(alias):
    """Archivo WAV que Windows usa para un sonido del sistema (p. ej. SystemAsterisk)."""
    try:
        import winreg
        clave = rf"AppEvents\Schemes\Apps\.Default\{alias}\.Current"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave) as k:
            ruta = os.path.expandvars(winreg.QueryValue(k, None))
        if ruta and Path(ruta).exists():
            return Path(ruta)
    except Exception:
        pass
    respaldo = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Media" / "Windows Background.wav"
    return respaldo if respaldo.exists() else None


def _sonido_sistema(alias, ganancia):
    """El WAV del sistema con el volumen aplicado (None si no se puede leer)."""
    ruta = _ruta_sonido_sistema(alias)
    if ruta is None:
        return None
    try:
        with wave.open(str(ruta), "rb") as w:
            if w.getsampwidth() != 2:
                return None
            canales, muestreo = w.getnchannels(), w.getframerate()
            datos = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767
        return _wav(datos * ganancia, canales, muestreo)
    except Exception:
        return None


SONIDOS = {
    # nombre: función(ganancia) -> bytes WAV
    "aviso": lambda g: _sonido_sistema("SystemAsterisk", g) or _tonos([(660, 120)], g),
    "timer_inicio": lambda g: _tonos([(1200, 90)], g),
    "timer_fin": lambda g: _tonos([(700, 90), (500, 120)], g),
    "anim_inicio": lambda g: _tonos([(880, 80), (1320, 80)], g),
    "anim_fin": lambda g: _tonos([(1320, 80), (880, 80)], g),
}


def _datos(nombre):
    clave = (nombre, volumen)
    with _lock:
        if clave not in _cache:
            _cache[clave] = SONIDOS[nombre](GANANCIAS.get(volumen, 0.28))
        return _cache[clave]


def reproducir(nombre):
    """Suena en segundo plano al volumen elegido. Fuera de Windows no hace nada."""
    if os.name != "nt" or nombre not in SONIDOS:
        return

    def _sonar():
        import winsound
        try:
            # SND_MEMORY no admite SND_ASYNC: por eso se reproduce en su propio hilo.
            winsound.PlaySound(_datos(nombre), winsound.SND_MEMORY)
        except Exception:
            pass
    threading.Thread(target=_sonar, daemon=True).start()
