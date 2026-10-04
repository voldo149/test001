# Capturador Silksong

App para Windows que hace dos cosas con el mando (XInput), sin pausar el juego:

- **Fotos:** captura de pantalla completa con un botón o combinación.
- **Temporizadores:** inicia y para con un botón o combinación, y guarda cuánto tiempo dedicaste a cada actividad (escribir, tomar fotos, etc.).

## Instalación (una sola vez)

1. Doble clic en **`instalar.bat`**. Instala las dependencias y crea el acceso directo **Capturador Silksong** con icono en el Escritorio y en el menú Inicio.
2. Para abrirla con **un clic**: busca "Capturador Silksong" en Inicio, haz clic derecho y elige **Anclar a la barra de tareas**.

## La ventana

Tiene un estilo oscuro inspirado en el editor de guías de Speedrunz. Se divide en tres columnas:

- **Izquierda:** fotos recientes en miniatura. Clic en una para abrirla.
- **Centro:** una tarjeta por temporizador, con el tiempo en grande y los totales de hoy, semana y total.
- **Derecha:** atajos de foto, formato, carpeta, sonidos y registro de actividad.

## Uso

- **+ Temporizador:** escribe el nombre de la actividad (por ejemplo, el juego). Se inicia y se para con el atajo de temporizador o con el botón **Iniciar / Parar** de su tarjeta.
- Mientras corre un temporizador, el título de la ventana en la barra de tareas muestra el tiempo.
- **+ Atajo de foto:** escribe un nombre y presiona el botón o la combinación.
- **Ver historial:** abre `tiempos.csv` en Excel, con una fila por sesión (actividad, inicio, fin, duración).
- Cada tarjeta muestra el tiempo de la sesión en marcha y los totales de hoy, de la semana y de siempre.

## Varios juegos con un solo atajo

- **Atajo de temporizador:** es uno solo para todos y se asigna en la columna derecha. Inicia o para el temporizador **seleccionado**.
- **Seleccionar:** haz clic en cualquier parte de una tarjeta. La seleccionada tiene borde verde y la etiqueta "SELECCIONADO". Al iniciar otro juego con el atajo, el que estaba corriendo se detiene y se guarda.
- **Fotos solo con temporizador activo** (activado por defecto): el atajo de foto solo funciona mientras hay un temporizador en marcha. Se apaga con el interruptor en "Atajos de foto".
- **Cancelar:** aparece en la tarjeta mientras corre. Descarta la sesión actual como si nunca hubiera pasado, por ejemplo si lo dejaste corriendo por accidente. Pide confirmación y no toca las sesiones anteriores.

## Si se cierra o se apaga la PC

- **Cierras la ventana:** los temporizadores se detienen y se guardan.
- **Cierre inesperado o apagón:** cada 30 s se anota qué está corriendo. Al abrir la app otra vez, la sesión se guarda hasta ese momento y te avisa cuánto recuperó.
- **La PC se suspende:** al despertar, los temporizadores se detienen en el momento en que se suspendió, así no cuentan el tiempo dormida.

## Para que no se pause ni se ponga lento

- La ventana nunca se pone al frente ni le quita el foco al juego. Ábrela antes y luego haz clic en el juego.
- Pon el juego en **pantalla completa sin bordes**.
- La captura usa DXGI (dxcam) y se guarda en un hilo aparte. El proceso corre con prioridad baja.

## Archivos (en esta carpeta, no se suben a git)

- `config.json`: atajos, temporizadores y ajustes.
- `tiempos.csv`: historial de sesiones.
- `en_curso.json`: temporizadores en marcha (para recuperar tras un cierre inesperado).
- `errores.log`: solo si algo falla.

## Versión de consola

`py capturador.py` sigue funcionando igual que antes (solo fotos).
