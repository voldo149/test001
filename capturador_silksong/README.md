# Capturador Silksong

App para Windows que hace esto con el mando (XInput), sin pausar el juego:

- **Fotos:** captura de pantalla completa con un botón o combinación.
- **Animaciones:** secuencias de imágenes a 60 fps. Un atajo empieza a grabar y el mismo atajo termina.
- **Temporizadores:** inicia y para con un botón o combinación, y guarda cuánto tiempo dedicaste a cada actividad (escribir, tomar fotos, etc.).

## Instalación (una sola vez)

1. Doble clic en **`instalar.bat`**. Instala las dependencias y crea el acceso directo **Capturador Silksong** con icono en el Escritorio y en el menú Inicio.
2. Para abrirla con **un clic**: busca "Capturador Silksong" en Inicio, haz clic derecho y elige **Anclar a la barra de tareas**. Ánclala desde Inicio, no desde la ventana abierta: así el icono anclado y la ventana son el mismo en la barra de tareas.

## La ventana

Tiene un estilo oscuro inspirado en el editor de guías de Speedrunz. Se divide en tres columnas:

- **Izquierda:** el **sufijo** de los archivos y las fotos recientes en miniatura. Clic en una para abrirla. Las animaciones aparecen como una sola miniatura (su primer cuadro) con la etiqueta ▶ y el número de cuadros. Al hacer clic se abre su carpeta.
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

## Nombres de archivo

Arriba de las miniaturas está el campo **Sufijo** (por ejemplo `doric`):

- Fotos: `doric-001.png`, `doric-002.png`, … (sigue el número más alto que ya exista).
- Animaciones: cada una en su subcarpeta `anim01`, `anim02`, … con `doric-anim01-001.png`, `doric-anim01-002.png`, …

## Animaciones (60 fps)

- Asigna el **Atajo de animación** en la columna derecha. Presiónalo una vez para empezar (suena un tono que sube) y otra para terminar (suena un tono que baja). Mientras graba, arriba aparece **● REC** con el tiempo y los cuadros.
- Si la pantalla no cambió en un cuadro, se repite el anterior, así la secuencia siempre dura lo mismo que en la realidad.
- Los cuadros esperan en memoria y se guardan con hilos de prioridad mínima mientras grabas y después de parar, para no quitarle fluidez al juego. Si se llega al límite de memoria (35 % de la RAM, máximo 6 GB), la grabación se detiene sola.
- Ocupan bastante espacio: a 1080p en PNG son unos 150–250 MB por segundo. En JPG mucho menos.
- Igual que las fotos, solo funciona con un temporizador en marcha si ese interruptor está activado. Mientras se graba una animación, el atajo de foto no hace nada.
- Si cierras la app mientras guarda, espera a terminar antes de cerrarse.

## Resolución y prioridad

- **Resolución** (columna derecha, en Formato): **Nativa** guarda tal cual la pantalla. **720p** captura igual y después la reduce a 720 px de alto, manteniendo la proporción. Reducir no cuesta más: comprimir una imagen de 720p es tanto más rápido que el total baja cerca de un 30 %. Cada animación conserva la resolución con la que empezó.
- **Prioridad** (arriba, junto al estado del mando). Se puede cambiar en cualquier momento, incluso mientras se guarda una animación:
  - **Juego:** la app corre con prioridad baja y guarda con pocos hilos de prioridad mínima. El juego va fluido y las animaciones tardan más en guardarse.
  - **Grabación:** prioridad normal, el hilo de captura con prioridad alta y todos los núcleos menos uno guardando. Se guarda lo más rápido posible y la captura a 60 fps es más estable. El juego puede ir algo más lento.

## Si se cierra o se apaga la PC

- **Cierras la ventana:** los temporizadores se detienen y se guardan.
- **Cierre inesperado o apagón:** cada 30 s se anota qué está corriendo. Al abrir la app otra vez, la sesión se guarda hasta ese momento y te avisa cuánto recuperó.
- **La PC se suspende:** al despertar, los temporizadores se detienen en el momento en que se suspendió, así no cuentan el tiempo dormida.

## Para que no se pause ni se ponga lento

- La ventana nunca se pone al frente ni le quita el foco al juego. Ábrela antes y luego haz clic en el juego.
- Pon el juego en **pantalla completa sin bordes**.
- La captura usa DXGI (dxcam) y se guarda en un hilo aparte. En modo de prioridad **Juego** el proceso corre con prioridad baja.

## Archivos (en esta carpeta, no se suben a git)

- `config.json`: atajos, temporizadores y ajustes.
- `tiempos.csv`: historial de sesiones.
- `en_curso.json`: temporizadores en marcha (para recuperar tras un cierre inesperado).
- `errores.log`: solo si algo falla.

## Versión de consola

`py capturador.py` sigue funcionando igual que antes (solo fotos).
