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

- **Izquierda:** el **sufijo** de los archivos y las fotos recientes en miniatura. Clic en una para abrirla. Las animaciones aparecen como una sola miniatura (su primer cuadro) con la etiqueta ▶ y el número de cuadros.
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

Fotos y animaciones **comparten la numeración**, así siempre sabes en qué orden se tomaron:

```
doric-001.webp
doric-002.webp
doric-anim_003/      ← animación: doric-anim_003-001.webp, -002.webp, … y doric-anim_003.avif
doric-004.webp
```

El número se aparta en el momento en que presionas el botón, así se respeta el orden aunque una animación todavía se esté guardando.

Las animaciones, según **Guardar como**:
- **Ambos** (por defecto): la carpeta con todos los cuadros sueltos y el `.avif` animado adentro. Los cuadros quedan como respaldo.
- **AVIF animado:** solo el archivo `doric-anim_003.avif`, junto a las fotos.
- **Cuadros:** solo la carpeta de cuadros.

## Animaciones (60 fps)

- Asigna el **Atajo de animación** en la columna derecha. Presiónalo una vez para empezar (suena un tono que sube) y otra para terminar (suena un tono que baja). Mientras graba, arriba aparece **● REC** con el tiempo y los cuadros.
- **Fluidez:** se toma cada cuadro que el juego muestra, en el momento en que aparece (se revisa cada ~1 ms). Si el juego tarda más en mostrar el siguiente (una escena a 30 fps o la pantalla quieta), el cuadro anterior se repite para que la animación dure lo mismo que en la realidad. En el `.avif` esos repetidos casi no pesan. Si tu monitor va a más de 60 Hz, se toma un cuadro por cada 1/60 de segundo. Para que salga perfecta, limita el juego a 60 fps.
- **Para no frenar la captura**, la compresión ocurre en procesos aparte. Python no deja que dos hilos del mismo proceso trabajen a la vez mientras se comprime WebP o JPG (medido: hasta 60 ms con WebP), y eso hacía que se perdieran cuadros. Ahora el hilo de captura solo toma el cuadro y lo pasa a memoria compartida.
- Los cuadros esperan en memoria mientras se comprimen, durante la grabación y después de parar. Si se llega al límite de memoria (35 % de la RAM, máximo 6 GB), la grabación se detiene sola.
- En PNG ocupan bastante: a 1080p son unos 150–250 MB por segundo. En WEBP, alrededor de una décima parte.
- Igual que las fotos, solo funciona con un temporizador en marcha si ese interruptor está activado. Mientras se graba una animación, el atajo de foto no hace nada.
- Si cierras la app mientras guarda, espera a terminar antes de cerrarse.

## Animaciones para la guía: AVIF animado

Medido con 2 segundos a 60 fps, 720p, la cámara recorriendo una escena del juego:

| Cómo se guarda | Tamaño |
|---|---|
| 120 PNG sueltos | 69.5 MB |
| GIF animado | 37.3 MB (y solo 256 colores) |
| 120 WEBP sueltos | 5.5 MB |
| WEBP animado | 5.6 MB (no aprovecha lo que se repite entre cuadros) |
| **AVIF animado** | **0.15 MB**, con la misma calidad que el WEBP |

El AVIF usa el mismo tipo de compresión que el video (AV1): solo guarda lo que cambia entre cuadros. Se reproduce solo y en bucle, como un GIF, en Chrome, Edge, Firefox y Safari. Con escenas de juego reales con más movimiento la ventaja será menor, pero sigue siendo enorme. Antes de usarlo, confirma que el editor de la guía acepta `.avif`. Si no, elige **Cuadros**.

Necesita Pillow 11.3 o más nuevo; `instalar.bat` lo actualiza. Se crea después de guardar los cuadros, leyéndolos de uno en uno, así no necesita tener toda la animación en memoria.

## Formato: PNG, JPG o WEBP

Medido con una captura real del juego a 1080p:

| Formato | Tamaño | Calidad |
|---|---|---|
| PNG | 1.74 MB | idéntica al original |
| JPG (calidad 95) | 0.45 MB | casi idéntica |
| **WEBP (calidad 90)** | **0.20 MB** | casi idéntica, igual que el JPG 95 |

**Para subir a la guía, WEBP es lo recomendado:** pesa un 10 % de un PNG y la mitad que un JPG con la misma calidad visible, y todos los navegadores actuales lo muestran. PNG solo vale la pena si necesitas el original exacto, por ejemplo para editarlo. Las animaciones también se guardan en el formato elegido.

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
