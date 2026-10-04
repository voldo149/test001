# Doble clic aquí (o en el acceso directo) para abrir la app sin consola.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app_gui import main
except ImportError as e:
    # Con pythonw no hay consola: avisar en una ventana.
    from tkinter import Tk, messagebox
    Tk().withdraw()
    messagebox.showerror("Capturador Silksong",
                         f"Falta una dependencia ({e.name}).\n\nEjecuta instalar.bat otra vez.")
    sys.exit(1)

main()
