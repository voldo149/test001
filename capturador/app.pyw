# Doble clic aquí (o en el acceso directo) para abrir la app sin consola.
import os
import sys

# Todo va dentro del if: los procesos que comprimen imágenes vuelven a leer este
# archivo al arrancar y no deben abrir otra ventana.
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from app_gui import main
    except ImportError as e:
        # Con pythonw no hay consola: avisar en una ventana.
        from tkinter import Tk, messagebox
        Tk().withdraw()
        messagebox.showerror("Capturador",
                             f"Falta una dependencia ({e.name}).\n\nEjecuta instalar.bat otra vez.")
        sys.exit(1)
    main()
