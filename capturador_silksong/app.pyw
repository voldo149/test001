# Doble clic aquí (o en el acceso directo) para abrir la app sin consola.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_gui import main

main()
