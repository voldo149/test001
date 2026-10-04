# Capturador Silksong

Toma capturas de pantalla completa con un botón (o combinación) del mando, sin pausar el juego. Solo funciona en Windows, porque usa XInput.

## Instalación

```
pip install -r requirements.txt
```

## Uso

Doble clic en `capturador.py`, o desde la terminal:

```
python capturador.py            # menú
python capturador.py agregar    # "presiona el botón con el que tomaremos fotos"
python capturador.py iniciar    # empieza a escuchar el mando
python capturador.py listar
python capturador.py borrar foto1
python capturador.py probar     # muestra qué botones detecta
```

Puedes tener varios atajos. Si dos se completan a la vez, gana el que tiene más botones.

## Para que no se pause ni se ponga lento

- Inicia el capturador **antes** y luego haz clic en el juego. El programa no abre ventanas ni le quita el foco al juego.
- Pon el juego en **pantalla completa sin bordes** (borderless). En pantalla completa exclusiva, algunas capturas pueden salir negras.
- Con `dxcam` instalado la captura usa DXGI, que es más rápido. Si no está, se usa `mss`.
- La imagen se guarda en un hilo aparte (PNG con compresión rápida). Si quieres archivos más pequeños, cambia `"formato": "jpg"` en `config.json`.
- El proceso corre con prioridad baja para no quitarle CPU al juego.

## config.json

Se crea al agregar el primer atajo. Opciones: `carpeta`, `formato`, `calidad_jpg`, `motor` (`auto`/`dxcam`/`mss`), `monitor`, `sonido` (apagado por defecto; también se cambia con la opción 6 del menú), `espera_entre_fotos`.
