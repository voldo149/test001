"""
Punto de entrada del .exe (PyInstaller).

`Capturador.exe --autoprueba [archivo]` comprueba que el .exe empaquetado
funciona (librerías, icono, procesos que comprimen, WebP y AVIF) sin abrir
ventanas, escribe el resultado en un archivo y sale con código 0 si todo
salió bien. Lo usa la compilación automática antes de crear el instalador.
"""

import multiprocessing
import os
import sys
import tempfile
import traceback
from pathlib import Path


def autoprueba(salida):
    lineas = []

    def ok(texto):
        lineas.append(f"OK  {texto}")

    try:
        import numpy as np
        from PIL import Image

        import animacion
        import app_gui  # noqa: F401  (importa customtkinter, tkinter y todo lo de la ventana)
        import aviso_pantalla  # noqa: F401
        import bandeja  # noqa: F401
        import capturador as cap
        import sonidos
        import trabajador
        ok(f"módulos de la app (versión {cap.VERSION})")

        import customtkinter  # noqa: F401
        import mss  # noqa: F401
        if os.name == "nt":  # solo existen en Windows
            import dxcam  # noqa: F401
            import pystray  # noqa: F401
            from win32com.shell import shell  # noqa: F401
            ok("customtkinter, mss, dxcam, pystray, pywin32")
        else:
            ok("customtkinter, mss (dxcam, pystray y pywin32 solo se revisan en Windows)")

        assert (cap.CARPETA_SCRIPT / "icono.ico").exists(), "falta icono.ico"
        ok(f"icono en {cap.CARPETA_SCRIPT}")
        assert animacion.avif_disponible(), "este Pillow no tiene AVIF"
        ok("Pillow con AVIF")
        assert sonidos._datos("timer_inicio")[:4] == b"RIFF"
        ok("sonidos")

        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(2, mp_context=multiprocessing.get_context("spawn")) as pool:
            pid = pool.submit(trabajador.calentar).result(timeout=180)
            ok(f"proceso que comprime arrancó (pid {pid})")

            carpeta = Path(tempfile.mkdtemp())
            rutas = []
            for i in range(3):
                cuadro = np.zeros((720, 1280, 4), np.uint8)
                cuadro[..., 1] = 60 * i
                shm, forma = cap.copiar_a_memoria(("bgra", cuadro))
                ruta = carpeta / f"prueba-{i + 1:03d}.webp"
                try:
                    pool.submit(trabajador.guardar, shm.name, forma, str(ruta),
                                {"resolucion": "720p", "calidad_webp": 90}, "juego").result(timeout=120)
                finally:
                    cap.liberar_memoria(shm)
                rutas.append(str(ruta))
            assert all(Image.open(r).format == "WEBP" for r in rutas)
            ok("WebP guardado desde memoria compartida en otro proceso")

            destino = carpeta / "prueba.avif"
            pool.submit(trabajador.crear_avif, rutas, str(destino), 60, 2, "juego").result(timeout=180)
            assert Image.open(destino).n_frames == 3
            ok("AVIF animado")
        codigo = 0
    except Exception:
        lineas.append("ERROR\n" + traceback.format_exc())
        codigo = 1
    Path(salida).write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return codigo


if __name__ == "__main__":
    multiprocessing.freeze_support()  # necesario para los procesos que comprimen dentro del .exe
    if "--autoprueba" in sys.argv:
        i = sys.argv.index("--autoprueba")
        destino = sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.join(tempfile.gettempdir(),
                                                                              "capturador_autoprueba.txt")
        sys.exit(autoprueba(destino))
    from app_gui import main
    main()
