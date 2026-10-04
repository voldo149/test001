"""Genera icono.ico (cámara con un reloj como lente). Solo hace falta si quieres rehacerlo."""

from pathlib import Path

from PIL import Image, ImageDraw

S = 256
FONDO = (30, 30, 46)
CUERPO = (236, 236, 244)
ACENTO = (220, 60, 80)


def dibujar():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=52, fill=FONDO)
    # Cuerpo de la cámara y visor
    d.rounded_rectangle((90, 62, 166, 92), radius=10, fill=CUERPO)
    d.rounded_rectangle((36, 80, 220, 206), radius=26, fill=CUERPO)
    d.ellipse((182, 94, 202, 114), fill=ACENTO)
    # Lente = reloj
    cx, cy, r = 128, 145, 50
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=FONDO)
    d.ellipse((cx - r + 9, cy - r + 9, cx + r - 9, cy + r - 9), fill=CUERPO)
    d.line((cx, cy, cx, cy - 28), fill=FONDO, width=8)
    d.line((cx, cy, cx + 20, cy + 8), fill=ACENTO, width=8)
    d.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=FONDO)
    return img


if __name__ == "__main__":
    ruta = Path(__file__).resolve().parent / "icono.ico"
    dibujar().save(ruta, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Icono guardado en {ruta}")
