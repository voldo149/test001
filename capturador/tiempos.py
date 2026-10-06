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
        self.tramos = {}       # actividad -> [(inicio, fin)] de esta sesión, aún sin pasar al CSV
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
        self._escribir(actividad, inicio, fin)
        self.sesiones.append((actividad, inicio, fin))

    def _escribir(self, actividad, inicio, fin):
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

    def _recuperar(self):
        if not self.archivo_en_curso.exists():
            return
        try:
            datos = json.loads(self.archivo_en_curso.read_text(encoding="utf-8"))
            latido = datetime.fromisoformat(datos["latido"])
            salvado = {}
            for actividad, tramos in datos.get("tramos", {}).items():  # tramos antes de pausas
                for inicio_txt, fin_txt in tramos:
                    inicio, fin = datetime.fromisoformat(inicio_txt), datetime.fromisoformat(fin_txt)
                    self._anotar(actividad, inicio, fin)
                    salvado[actividad] = salvado.get(actividad, timedelta()) + (fin - inicio)
            for actividad, inicio_txt in datos.get("timers", {}).items():
                inicio = datetime.fromisoformat(inicio_txt)
                if latido > inicio:
                    self._anotar(actividad, inicio, latido)
                    salvado[actividad] = salvado.get(actividad, timedelta()) + (latido - inicio)
            self.recuperadas.extend(salvado.items())
        except (ValueError, KeyError, OSError):
            pass
        self.archivo_en_curso.unlink(missing_ok=True)

    def latido(self, ahora=None):
        """Guarda qué temporizadores están en marcha (llamar cada ~30 s)."""
        if not self.en_curso and not any(self.tramos.values()):
            self.archivo_en_curso.unlink(missing_ok=True)
            return
        ahora = ahora or datetime.now()
        self.ultimo_latido = ahora
        datos = {
            "latido": ahora.isoformat(timespec="seconds"),
            "timers": {a: i.isoformat(timespec="seconds") for a, i in self.en_curso.items()},
            "tramos": {a: [[i.isoformat(timespec="seconds"), f.isoformat(timespec="seconds")] for i, f in t]
                       for a, t in self.tramos.items() if t},
        }
        self.archivo_en_curso.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    # ---------------------------------------------------------------- control
    # Pausa: el tramo hasta la pausa se cierra y, al reanudar, empieza otro. Así los totales
    # son exactos y el reloj de la tarjeta suma los tramos. Los tramos pasan al CSV al
    # parar (cancelar los descarta todos); mientras tanto el latido los protege.

    def corriendo(self, actividad):
        return actividad in self.en_curso

    def en_pausa(self, actividad):
        return actividad in self.pausados

    def iniciar(self, actividad, momento=None, continuar=False):
        if actividad not in self.en_curso:
            if not continuar:
                self.previo.pop(actividad, None)
                for inicio, fin in self.tramos.pop(actividad, []):  # restos de otra sesión
                    self._escribir(actividad, inicio, fin)
            self.pausados.discard(actividad)
            self.en_curso[actividad] = momento or datetime.now()
            self.latido(momento)

    def parar(self, actividad, momento=None):
        """Detiene y guarda. Devuelve la duración del último tramo (timedelta) o None."""
        self.pausados.discard(actividad)
        self.previo.pop(actividad, None)
        duracion = self._cerrar_tramo(actividad, momento)
        for inicio, fin in self.tramos.pop(actividad, []):
            self._escribir(actividad, inicio, fin)
        self.latido()
        return duracion

    def _cerrar_tramo(self, actividad, momento):
        inicio = self.en_curso.pop(actividad, None)
        if inicio is None:
            return None
        fin = max(momento or datetime.now(), inicio)
        if fin > inicio:
            self.tramos.setdefault(actividad, []).append((inicio, fin))
            self.sesiones.append((actividad, inicio, fin))  # ya cuenta en los totales
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
        """Descarta la sesión entera (todos sus tramos) como si nunca hubiera pasado.
        Devuelve lo descartado."""
        inicio = self.en_curso.pop(actividad, None)
        self.previo.pop(actividad, None)
        self.pausados.discard(actividad)
        tramos = self.tramos.pop(actividad, [])
        for i, f in tramos:
            self.sesiones.remove((actividad, i, f))
        if inicio is None and not tramos:
            return None
        self.latido()
        descartado = sum((f - i for i, f in tramos), timedelta())
        return descartado + (datetime.now() - inicio if inicio else timedelta())

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
