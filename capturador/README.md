# Capturador

App para Windows que hace esto con el mando (XInput), sin pausar el juego:

- **Fotos:** captura de pantalla completa con un botón o combinación.
- **Animaciones:** secuencias de imágenes a 60 fps. Un atajo empieza a grabar y el mismo atajo termina.
- **Temporizadores:** inicia y para con un botón o combinación, y guarda cuánto tiempo dedicaste a cada actividad (escribir, tomar fotos, etc.).

## Número de versión

Se ve arriba a la izquierda, junto a "Fotos y tiempos" (por ejemplo **v1.8**), y en la primera línea de Actividad. El instalador se llama `Capturador-Setup-1.8.exe`. Así sabes si ya tienes la última.

## Instalador (.exe)

La forma más fácil, sin instalar Python ni Git: **`Capturador-Setup.exe`**.
- Lo genera GitHub automáticamente en una máquina Windows cada vez que se suben cambios. Antes de crear el instalador prueba que el .exe funcione (librerías, procesos que comprimen, WebP y AVIF).
- Para descargarlo: en GitHub, pestaña **Actions** → "Capturador para Windows" → la ejecución más reciente con ✓ → **Artifacts** → `Capturador-Setup` (viene en un .zip).
- Se instala solo para tu usuario (no pide administrador), con acceso directo en Inicio y, si quieres, en el escritorio y al iniciar Windows.
- En la versión instalada, la configuración y los tiempos se guardan en `%APPDATA%\Capturador`. La primera vez copia los de una instalación desde el código (`test001\capturador`), si existe.
- Para actualizar: descarga el instalador nuevo y ejecútalo encima. Si la app está abierta, te pide cerrarla.

## Instalación desde cero (en una PC nueva)

1. Abre **CMD** (tecla Windows, escribe `cmd`, Enter) e instala Git y Python:
   ```cmd
   winget install -e --id Git.Git
   winget install -e --id Python.Python.3.12
   ```
   **Cierra CMD y ábrelo otra vez** para que reconozca los programas nuevos.
2. Descarga la app:
   ```cmd
   cd %USERPROFILE%
   git clone -b claude/adoring-darwin-pktdfp https://github.com/voldo149/test001.git
   cd test001\capturador
   ```
   Si el repositorio es privado, GitHub pide iniciar sesión con una cuenta que tenga acceso.
3. Escribe `instalar.bat` y Enter. Instala todo y crea el acceso directo **Capturador** en el Escritorio y en Inicio.
4. Para abrirla con un clic: busca "Capturador" en **Inicio**, clic derecho, **Anclar a la barra de tareas**.

**Si venías de la versión con la carpeta `capturador_silksong`:** después de `git pull` la app está en `test001\capturador`. Corre `instalar.bat` desde ahí: crea los accesos nuevos, borra los viejos y arregla el icono anclado. La primera vez que la abras copia tu configuración y tus tiempos de la carpeta vieja; después puedes borrar `capturador_silksong`.

**Para actualizar después:** cierra la app y en CMD:
```cmd
cd %USERPROFILE%\test001\capturador
git pull
instalar.bat
```

**Primera configuración en la app:** "+ Temporizador" (el juego), asigna el **Atajo de temporizador**, el **Atajo de foto** y el **Atajo de animación**, elige la carpeta con 📁, escribe el **Sufijo** y elige **WEBP**. En el juego: **pantalla completa sin bordes**, HDR de Windows apagado y, para las animaciones, el juego limitado a 60 fps.

## Instalación (una sola vez)

1. Doble clic en **`instalar.bat`**. Instala las dependencias y crea el acceso directo **Capturador** con icono en el Escritorio y en el menú Inicio.
2. Para abrirla con **un clic**: busca "Capturador" en Inicio, haz clic derecho y elige **Anclar a la barra de tareas**. Ánclala desde Inicio, no desde la ventana abierta: así el icono anclado y la ventana son el mismo en la barra de tareas.

## La ventana

Tiene un estilo oscuro inspirado en el editor de guías de Speedrunz. Se divide en tres columnas:

- **Izquierda:** la carpeta en uso (botón 📁 para elegirla), el **sufijo** de los archivos y las fotos recientes en miniatura. Clic en una para abrirla. Las animaciones aparecen como una sola miniatura (su primer cuadro) con la etiqueta ▶ y el número de cuadros.
- **Centro:** una tarjeta por temporizador, con el tiempo en grande y los totales de hoy, semana y total.
- **Derecha:** atajos de foto, formato, carpeta, sonidos y registro de actividad.

## Uso

- **+ Temporizador:** escribe el nombre de la actividad (por ejemplo, el juego). Se inicia y se para con el atajo de temporizador o con el botón **Iniciar / Parar** de su tarjeta.
- Mientras corre un temporizador, el título de la ventana en la barra de tareas muestra el tiempo.
- **+ Atajo de foto:** aparece "Presiona el atajo": presiona un **botón del mando** (o mantén una combinación y suelta). Se guarda como "Atajo 1", "Atajo 2", etc. **Esc** o la **✕** salen sin asignar. La **✕** de cada atajo lo borra al instante, sin preguntar.
- **Por ahora los atajos son solo del mando** (el teclado se quitó mientras se revisa). Si tenías atajos con teclas, al abrir la app se quitan esas teclas y se avisa en Actividad.
- **Ver historial:** abre `tiempos.csv` en Excel, con una fila por sesión (actividad, inicio, fin, duración).
- Cada tarjeta muestra el tiempo de la sesión en marcha y los totales de hoy, de la semana y de siempre.

## Varios juegos con un solo atajo

- **Atajo de temporizador:** es uno solo para todos y se asigna en la columna derecha. Inicia o para el temporizador **seleccionado**.
- **Seleccionar:** haz clic en cualquier parte de una tarjeta. La seleccionada tiene borde verde y la etiqueta "SELECCIONADO". Al iniciar otro juego con el atajo, el que estaba corriendo se detiene y se guarda.
- **Fotos solo con temporizador activo** (activado por defecto): el atajo de foto solo funciona mientras hay un temporizador en marcha. Si lo intentas sin temporizador, suena el aviso de Windows ("Aviso si no hay temporizador", en Sonidos). Se apaga con el interruptor en "Atajos de foto".
- **Autoshot** (en Atajos de foto): toma una foto sola cada N segundos (− / + para elegir, de 1 a 60) mientras corre el temporizador. Puedes seguir tomando tus fotos normales. Las automáticas van a la **misma carpeta** y siguen la **misma numeración** que las manuales (`doric-014.webp` automática, `doric-015.webp` tuya, `doric-016.webp` automática…), sin repetir números. No hacen sonido, pero sí el **destello verde** del circulito (abajo a la izquierda) y aparecen en las miniaturas. No cuentan para la pausa automática, se detienen mientras el temporizador está en pausa y mientras grabas una animación.
- **Pausa automática sin fotos** (columna derecha, en Más opciones: No / 30 s / 1 / 3 / 5 min, por defecto 30 s): si pasa ese tiempo sin fotos ni animaciones, el temporizador se pone **en pausa** (gris) y **se cuenta solo hasta la última foto**. La siguiente foto lo reanuda. Solo se activa después de la primera foto de la sesión, así un temporizador en el que no tomas fotos (por ejemplo "escribir") nunca se pausa solo. Con el **autoshot** encendido no hay pausa automática (si no, se detendría el autoshot). En pausa, la tarjeta muestra **Reanudar** y **Terminar**.
- **Pausa mientras usas la app:** mientras la ventana del Capturador (o uno de sus diálogos, como el de recortar) está al frente, el tiempo **no cuenta** y el **autoshot se detiene**. La tarjeta dice "PAUSA: USANDO LA APP" y sigue con **Parar** y **Cancelar**, como si estuviera en marcha. Al volver al juego sigue sola. (Mientras grabas una animación no se pausa.)
- **Cancelar** descarta toda la sesión, también los tramos de antes de cada pausa. Los tramos pasan al historial (`tiempos.csv`) al parar el temporizador.
- **Cancelar:** aparece en la tarjeta mientras corre. Descarta la sesión actual como si nunca hubiera pasado, por ejemplo si lo dejaste corriendo por accidente. Pide confirmación y no toca las sesiones anteriores.

## Carpetas por juego

- El botón **📁** (arriba a la izquierda) elige dónde se guardan las fotos:
  - Con un temporizador **seleccionado**: esa carpeta es **solo para ese temporizador**. Debajo dice "Carpeta de «Silksong»".
  - Sin temporizador seleccionado: cambia la **carpeta general**.
- **Usar general:** aparece cuando el temporizador seleccionado tiene carpeta propia. La quita y vuelve a la general.
- Para quitar la selección de un temporizador, haz clic otra vez en su tarjeta.
- Las miniaturas muestran la carpeta en uso, y cada carpeta lleva su propia numeración.
- "Abrir fotos" (arriba a la derecha) abre la carpeta en uso. La **carpeta general** también se puede cambiar en la columna derecha.

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
- **Cuadros** (por defecto): solo la carpeta de cuadros. Después haces clic en su miniatura para **recortarla** y crear el AVIF (ver abajo).
- **Ambos:** la carpeta de cuadros y el `.avif` animado, creado en cuanto termina de grabar.
- **AVIF animado:** solo el archivo `doric-anim_003.avif`, junto a las fotos.

## Recortar y crear el AVIF

Clic en la miniatura de una animación (la que tiene la etiqueta ▶):
- Vista previa del cuadro, más las barras **Inicio** y **Final** para quitar los intentos fallidos y las esperas. Muestra cuántos cuadros y cuántos segundos quedan.
- Botones **−** y **+** a los lados de cada barra: un toque mueve un cuadro. Mantenido, después de 0.3 s avanza solo y va acelerando. Sirve sin mouse, por ejemplo con el touchpad.
- Los cuadros que borres a mano de la carpeta tampoco se usan, así puedes quitar partes del medio.
- **Guardar cuadro como foto:** guarda el cuadro que estás viendo como foto suelta (`doric-005.webp`), con el siguiente número. Es una copia exacta, sin volver a comprimir. Sirve para sacar la imagen perfecta de una animación.
- **Crear AVIF** guarda el tramo elegido como **la siguiente foto** (`doric-006.avif`, junto a las fotos), en un proceso aparte, y **el editor sigue abierto**. Así de una sola grabación (por ejemplo, toda una pelea con un jefe) sacas un AVIF por cada patrón de ataque: `doric-006.avif`, `doric-007.avif`, … Después de crear uno, el **Inicio** salta al cuadro siguiente al final que usaste, para seguir avanzando por la pelea. Debajo se listan los que ya creaste y de qué cuadros salió cada uno. **Cerrar** sale del editor.
- **Recortar carpeta de cuadros…** (columna derecha, en Atajo de animación): elige cualquier carpeta con cuadros (PNG, JPG o WEBP), por ejemplo una grabación vieja, y se abre este mismo editor. Los AVIF de una carpeta grabada con la app van junto a ella con su sufijo; los de otra carpeta, a la carpeta de guardado actual con el sufijo actual.

## Animaciones (60 fps)

- Asigna el **Atajo de animación** en la columna derecha. Presiónalo una vez para empezar (suena un tono que sube) y otra para terminar (suena un tono que baja). Mientras graba, arriba aparece **● REC** con el tiempo y los cuadros.
- **Fluidez:** se toma cada cuadro que el juego muestra, en el momento en que aparece (se revisa cada ~1 ms). Si el juego tarda más en mostrar el siguiente (una escena a 30 fps o la pantalla quieta), el cuadro anterior se repite para que la animación dure lo mismo que en la realidad. En el `.avif` esos repetidos casi no pesan. Si tu monitor va a más de 60 Hz, se toma un cuadro por cada 1/60 de segundo. Para que salga perfecta, limita el juego a 60 fps.
- **Para no frenar la captura**, la compresión ocurre en procesos aparte. Python no deja que dos hilos del mismo proceso trabajen a la vez mientras se comprime WebP o JPG (medido: hasta 60 ms con WebP), y eso hacía que se perdieran cuadros. Ahora el hilo de captura solo toma el cuadro y lo pasa a memoria compartida.
- **Sin límite de duración:** puedes grabar toda una pelea o muchos intentos seguidos y después sacar cada parte con el editor de recorte. Los cuadros esperan en memoria mientras se comprimen. Si se van juntando, se usan más procesos para comprimir. Si aun así la memoria pendiente llega al límite (35 % de la RAM, máximo 6 GB), se repite el cuadro anterior un momento (como si el juego se trabara) hasta que la PC se ponga al día. La grabación **nunca se detiene sola**. En Actividad se ve cuántos cuadros se repitieron por eso. Para evitarlo, graba en 720p.
- Mientras grabas, las fotos con botón y el autoshot no se toman.
- En PNG ocupan bastante: a 1080p son unos 150–250 MB por segundo. En WEBP, alrededor de una décima parte.
- Igual que las fotos, solo funciona con un temporizador en marcha si ese interruptor está activado. Mientras se graba una animación, el atajo de foto no hace nada.
- Si cierras la app mientras guarda, espera a terminar antes de cerrarse.
- **Diagnóstico:** al terminar, Actividad muestra un resumen (por ejemplo `2.05 s de animación para 2.03 s reales · juego ≈ 143 fps · monitor 144 Hz · 12 repetidos · 141 descartados · captura 1.4 ms`) y se guarda completo en `info.json` dentro de la carpeta.
- **Si se ve con tirones:** casi siempre es porque el juego va a más de 60 fps (monitor de 120/144 Hz). Al pasarlo a 60, cada cuadro de la animación avanza 2 o 3 cuadros del juego de forma desigual. Limita el juego a 60 fps mientras grabas: en las opciones del juego, en el panel de NVIDIA/AMD ("Velocidad máxima de fotogramas" para Silksong) o poniendo el monitor a 60 Hz. Revisa también el AVIF en Chrome o Edge (arrastra el archivo al navegador), porque algunos visores reproducen las animaciones más lento.

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

## Indicador en pantalla

Un circulito abajo a la izquierda:
- **Gris:** hay un temporizador corriendo.
- **Rojo:** grabando una animación.
- **Destello verde** (~0.3 s): se tomó una foto.
- **No aparece** si no hay temporizador corriendo (detenido o en pausa).

- **No sale en las capturas:** Windows lo excluye de cualquier captura (también de Greenshot u OBS). Requiere Windows 10 versión 2004 o más nuevo. Si no se puede, el indicador se desactiva solo.
- No toma el foco ni recibe clics, así que el juego no se pausa. Se ve encima del juego en **pantalla completa sin bordes**.
- Se apaga en Sonidos → "Indicador en pantalla".

## Volumen

En Sonidos, la **barrita de 5 niveles** controla el volumen de todos los sonidos de la app (el aviso de "sin temporizador", el pitido del temporizador, los tonos de la animación y el sonido de foto), sin tocar el volumen de Windows. Al tocar una barra suena una prueba. El aviso sigue siendo el mismo sonido de Windows, pero con el volumen escalado.

## Bandeja del sistema e inicio con Windows

- La app pone su icono junto al reloj. Doble clic: abrir. Clic derecho: **Abrir** / **Salir**. Al pasar el mouse muestra el temporizador en marcha.
- **Iniciar con Windows**, en la columna derecha: al prender la PC la app se abre escondida en la bandeja, lista para el mando.
- Si la abres otra vez (por ejemplo desde la barra de tareas) mientras ya está en la bandeja, se muestra la que ya estaba abierta en vez de abrir otra copia.

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
