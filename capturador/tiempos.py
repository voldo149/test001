"""
Registro de temporizadores.

- Cada sesión terminada se agrega a tiempos.csv (se abre con Excel).
- Los temporizadores en marcha se anotan en en_curso.json junto con un
  "latido" que la app actualiza cada 30 s. Si la app se cierra de golpe
  (o se apaga la PC), al abrirla otra vez la sesión se guarda hasta el
  último latido en vez de perderse o contar horas de más.
"""

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

COLUMNAS = ["actividad", "inicio", "fin", "duracion", "segundos"]


def formato_duracion(segundos):
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}"


class RegistroTiempos:
    def __init__(self, carpeta):
        carpeta = Path(carpeta)
        self.archivo = carpeta / "tiempos.csv"
        self.archivo_en_curso = carpeta / "en_curso.json"
        self.sesiones = []   # [(actividad, inicio, fin)]
        self.en_curso = {}   # actividad -> inicio
        self.pausados = set()  # en pausa automática (no cuentan, pero la sesión sigue)
        self.previo = {}       # actividad -> segundos de tramos anteriores de esta sesión
        self.recuperadas = []  # sesiones salvadas de un cierre inesperado
        self.ultimo_latido = None
        self._cargar()
        self._recuperar()

    # ---------------------------------------------------------------- archivo

    def _cargar(self):
        if not self.archivo.exists():
            return
        with open(self.archivo, encoding="utf-8-sig", newline="") as f:
            for fila in csv.DictReader(f):
                try:
                    self.sesiones.append((
                        fila["actividad"],
                        datetime.fromisoformat(fila["inicio"]),
                        datetime.fromisoformat(fila["fin"]),
                    ))
                except (KeyError, ValueError):
                    continue  # fila editada a mano o dañada: se ignora

    def _anotar(self, actividad, inicio, fin):
        nuevo = not self.archivo.exists()
        with open(self.archivo, "a", encoding="utf-8-sig" if nuevo else "utf-8", newline="") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(COLUMNAS)
            seg = (fin - inicio).total_seconds()
            w.writerow([
                actividad,
                inicio.isoformat(timespec="seconds"),
                fin.isoformat(timespec="seconds"),
                formato_duracion(seg),
                int(seg),
            ])
        self.sesiones.append((actividad, inicio, fin))

    def _recuperar(self):
        if not self.archivo_en_curso.exists():
            return
        try:
            datos = json.loads(self.archivo_en_curso.read_text(encoding="utf-8"))
            latido = datetime.fromisoformat(datos["latido"])
            for actividad, inicio_txt in datos.get("timers", {}).items():
                inicio = datetime.fromisoformat(inicio_txt)
                if latido > inicio:
                    self._anotar(actividad, inicio, latido)
                    self.recuperadas.append((actividad, latido - inicio))
        except (ValueError, KeyError, OSError):
            pass
        self.archivo_en_curso.unlink(missing_ok=True)

    def latido(self, ahora=None):
        """Guarda qué temporizadores están en marcha (llamar cada ~30 s)."""
        if not self.en_curso:
            self.archivo_en_curso.unlink(missing_ok=True)
            return
        ahora = ahora or datetime.now()
        self.ultimo_latido = ahora
        datos = {
            "latido": ahora.isoformat(timespec="seconds"),
            "timers": {a: i.isoformat(timespec="seconds") for a, i in self.en_curso.items()},
        }
        self.archivo_en_curso.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    # ---------------------------------------------------------------- control
    # Pausa: el tramo hasta la pausa se guarda como una sesión y, al reanudar, empieza
    # otro tramo. Así los totales son exactos y el reloj de la tarjeta suma los tramos.

    def corriendo(self, actividad):
        return actividad in self.en_curso

    def en_pausa(self, actividad):
        return actividad in self.pausados

    def iniciar(self, actividad, momento=None, continuar=False):
        if actividad not in self.en_curso:
            if not continuar:
                self.previo.pop(actividad, None)
            self.pausados.discard(actividad)
            self.en_curso[actividad] = momento or datetime.now()
            self.latido(momento)

    def parar(self, actividad, momento=None):
        """Detiene y guarda. Devuelve la duración del último tramo (timedelta) o None."""
        self.pausados.discard(actividad)
        self.previo.pop(actividad, None)
        return self._cerrar_tramo(actividad, momento)

    def _cerrar_tramo(self, actividad, momento):
        inicio = self.en_curso.pop(actividad, None)
        if inicio is None:
            return None
        fin = max(momento or datetime.now(), inicio)
        self._anotar(actividad, inicio, fin)
        self.latido(fin)
        return fin - inicio

    def pausar(self, actividad, momento=None):
        """Deja de contar desde `momento` (puede ser en el pasado) sin detener del todo."""
        duracion = self._cerrar_tramo(actividad, momento)
        if duracion is None:
            return None
        self.previo[actividad] = self.previo.get(actividad, 0.0) + duracion.total_seconds()
        self.pausados.add(actividad)
        return duracion

    def reanudar(self, actividad, momento=None):
        if actividad in self.pausados:
            self.iniciar(actividad, momento, continuar=True)

    def cancelar(self, actividad):
        """Descarta el tramo en marcha como si nunca hubiera pasado. Devuelve lo descartado."""
        inicio = self.en_curso.pop(actividad, None)
        self.previo.pop(actividad, None)
        if inicio is None:
            return None
        self.latido()
        return datetime.now() - inicio

    def alternar(self, actividad, momento=None):
        """Inicia (o reanuda) o detiene. Devuelve (corriendo_ahora, duracion_si_paro)."""
        if self.corriendo(actividad):
            return False, self.parar(actividad, momento)
        if self.en_pausa(actividad):
            self.reanudar(actividad, momento)
            return True, None
        self.iniciar(actividad, momento)
        return True, None

    def parar_todos(self, momento=None):
        for a in list(self.pausados):
            self.parar(a)
        return {a: self.parar(a, momento) for a in list(self.en_curso)}

    def sesion(self, actividad, ahora=None):
        """Segundos de la sesión actual: tramos antes de las pausas + el tramo en marcha."""
        return self.previo.get(actividad, 0.0) + self.actual(actividad, ahora)

    # ---------------------------------------------------------------- totales

    def actual(self, actividad, ahora=None):
        inicio = self.en_curso.get(actividad)
        if inicio is None:
            return 0.0
        return max(((ahora or datetime.now()) - inicio).total_seconds(), 0.0)

    def total(self, actividad, desde=None, ahora=None):
        """Segundos acumulados (incluye la sesión en marcha), opcionalmente desde una fecha."""
        ahora = ahora or datetime.now()
        tramos = [(i, f) for a, i, f in self.sesiones if a == actividad]
        if actividad in self.en_curso:
            tramos.append((self.en_curso[actividad], ahora))
        total = 0.0
        for inicio, fin in tramos:
            if desde is not None:
                inicio = max(inicio, desde)
            total += max((fin - inicio).total_seconds(), 0.0)
        return total

    def total_hoy(self, actividad, ahora=None):
        ahora = ahora or datetime.now()
        return self.total(actividad, desde=ahora.replace(hour=0, minute=0, second=0, microsecond=0), ahora=ahora)

    def total_semana(self, actividad, ahora=None):
        ahora = ahora or datetime.now()
        lunes = (ahora - timedelta(days=ahora.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.total(actividad, desde=lunes, ahora=ahora)
