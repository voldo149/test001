# Capturador Silksong

App para Windows que hace dos cosas con el mando (XInput), sin pausar el juego:

- **Fotos:** captura de pantalla completa con un botón o combinación.
- **Temporizadores:** inicia y para con un botón o combinación, y guarda cuánto tiempo dedicaste a cada actividad (escribir, tomar fotos, etc.).

## Instalación (una sola vez)

1. Doble clic en **`instalar.bat`**. Instala las dependencias y crea el acceso directo **Capturador Silksong** con icono en el Escritorio y en el menú Inicio.
2. Para abrirla con **un clic**: busca "Capturador Silksong" en Inicio, haz clic derecho y elige **Anclar a la barra de tareas**.

## Uso

- **Temporizadores → Nuevo:** escribe el nombre de la actividad y, si quieres, presiona el botón del mando que la va a iniciar y parar. También puedes iniciarla o pararla con el botón **Iniciar / Parar** o con doble clic en la fila.
- Mientras corre un temporizador, el título de la ventana en la barra de tareas muestra el tiempo.
- **Fotos → Agregar atajo:** escribe un nombre y presiona el botón o la combinación.
- **Ver historial:** abre `tiempos.csv` en Excel, con una fila por sesión (actividad, inicio, fin, duración).
- La tabla muestra el tiempo de la sesión en marcha y los totales de hoy, de la semana y de siempre.
- Si la app se cierra de golpe o se apaga la PC, al abrirla otra vez la sesión se guarda hasta el último momento registrado (cada 30 s).
- Al cerrar la ventana, los temporizadores en marcha se detienen y se guardan.

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
