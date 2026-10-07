"""
Trabajo pesado en procesos aparte: comprimir imágenes y crear el AVIF.

Por qué procesos y no hilos: Pillow mantiene el GIL de Python mientras
comprime WebP o JPG (medido: hasta 60 ms con WebP y casi 1 s con JPG). Si
eso pasa en el mismo proceso que la captura, el hilo de captura se congela,
pierde cuadros y la animación se ve cortada. En otro proceso no hay GIL
compartido, así que la captura nunca espera.

Los cuadros llegan por memoria compartida (sin copiarlos por un tubo).
"""

import ctypes
import os
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np
from PIL import Image

import capturador as cap

_PROCESO = {"juego": 0x00004000, "grabacion": 0x00000020}  # BELOW_NORMAL / NORMAL
_HILO = {"juego": -2, "grabacion": 0}                       # LOWEST / NORMAL


_nice_aplicado = None


def _prioridad(modo):
    global _nice_aplicado
    if os.name == "nt":
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), _PROCESO.get(modo, 0x00004000))
        k32.SetThreadPriority(k32.GetCurrentThread(), _HILO.get(modo, 0))
    elif _nice_aplicado is None:
        # Fuera de Windows: ceder la CPU a la captura (solo se puede bajar, una vez).
        try:
            os.nice(15)
            _nice_aplicado = True
        except OSError:
            _nice_aplicado = False


def _leer(nombre_shm, forma):
    """Lee un cuadro BGRA de memoria compartida y devuelve una imagen RGB independiente."""
    shm = shared_memory.SharedMemory(name=nombre_shm)  # la libera el proceso que la creó
    try:
        arr = np.ndarray(forma, dtype=np.uint8, buffer=shm.buf)
        img = Image.frombuffer("RGB", (forma[1], forma[0]), arr, "raw", "BGRX", 0, 1)
        img.load()
        del arr
        return img
    finally:
        shm.close()


def calentar(*_):
    """Tarea vacía para arrancar un proceso antes de necesitarlo."""
    return os.getpid()


def guardar(nombre_shm, forma, ruta, opciones, modo, miniatura=None):
    """Guarda un cuadro o foto. Si se pide, devuelve una miniatura (tamaño, bytes RGB)."""
    _prioridad(modo)
    img = cap.ajustar_resolucion(_leer(nombre_shm, forma), opciones.get("resolucion"), opciones.get("rapido", False))
    cap.guardar_imagen(img, Path(ruta), opciones, rapido=opciones.get("rapido", False))
    if miniatura:
        img.thumbnail(miniatura)
        return img.size, img.tobytes()
    return None


def crear_avif(rutas, destino, fps, hilos, modo):
    import animacion
    _prioridad(modo)
    animacion.crear_avif([Path(r) for r in rutas], Path(destino), fps, hilos=hilos)
