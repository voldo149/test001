"""
Investigación de guías: qué busca la gente en Google (español e inglés).

Tres pasos:
  1. descubrir  -> búsquedas genéricas ("guia ...", "walkthrough for ...", "how to beat ...")
                   para ver QUÉ JUEGOS aparecen más, sin decirle ningún juego.
  2. juegos     -> para cada juego de la lista JUEGOS, todo lo que la gente busca de él.
  3. trends     -> (opcional) ranking de popularidad entre juegos con Google Trends.

Uso (en tu PC, con Python 3.9+):
  Doble clic en el archivo -> aparece un menú para elegir el paso.
  O desde la terminal:
  python investigar_guias.py descubrir
  python investigar_guias.py juegos
  python investigar_guias.py trends      (antes: pip install pytrends)
  python investigar_guias.py todo

Los resultados salen como .csv en la carpeta "resultados" (se abren con Excel).

Notas:
- El autocompletado dice QUÉ busca la gente y en qué orden de popularidad (posición 1 =
  lo más buscado para ese inicio), pero no CUÁNTAS búsquedas. Para volumen real, revisa
  las ideas ganadoras en Google Keyword Planner.
- Si Google empieza a fallar (error 429), espera un rato o sube PAUSA.
"""

import csv
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

# ===================== CONFIGURACIÓN =====================

IDIOMAS = {
    # código: (idioma, país)
    "es": ("es", "mx"),
    "en": ("en", "us"),
}

# Paso 1: inicios genéricos. Google completa con lo más buscado -> salen los juegos populares.
SEMILLAS_DESCUBRIR = {
    "es": ["guia ", "guia de ", "como pasar ", "como conseguir ", "donde encontrar ",
           "mejor build ", "trucos ", "como derrotar a ", "todos los coleccionables "],
    "en": ["guide ", "walkthrough for ", "how to beat ", "how to get ", "where to find ",
           "best build ", "tier list ", "all collectibles ", "100% guide "],
}

# Paso 2: juegos a investigar a fondo. Agrega o quita los que quieras.
# (Candidatos elegidos con el resultado del paso 1: juegos nuevos o actualizados
#  con muchas búsquedas, más Dragonwilds como base)
JUEGOS = [
    "palworld", "resident evil requiem", "007 first light", "expedition 33",
    "silksong", "battlefield 6", "pokemon za", "deltarune", "dragonwilds",
]

# Palabras que se añaden después del juego (además de a-z) en el paso 2
MODIFICADORES = {
    "es": ["guia", "como", "donde", "mejor", "todos", "trucos", "mapa"],
    "en": ["guide", "how to", "where", "best", "all", "map", "quest"],
}

# Filtro de ruido: sugerencias con estas palabras no son de juegos ("pasar fotos de un
# celular a otro", "guía de primaria"...). No se borran: van a *_descartadas.csv por si
# quieres revisarlas. Si una palabra te quita algo bueno, sácala de aquí.
RUIDO = """
celular celulares iphone android whatsapp fotos contactos esim wifi bateria pila cable cables usb
computadora instagram tiktok facebook seguidores youtube google gmail excel word pdf
primaria secundaria preparatoria grado matematicas fraccion decimal santillana uacj escuela
pesos dolares dollars quiniela progol 401k trabajo jobs credito
dhl fedex estafeta rastreo paquete vuelos tallas talla metros km
hipertension clinica protein grams calorias receta
crossword lyrics near_me
"""
PAUSA = (0.4, 0.9)          # segundos entre peticiones (al azar en ese rango)
LETRAS = "abcdefghijklmnopqrstuvwxyz0123456789"
CARPETA = Path(__file__).with_name("resultados")

# Palabras que no cuentan como "tema" al hacer el ranking
VACIAS = set("""
de del la las el los un una y o a en para por con que como donde mejor guia guía
the of to for a an and in on how where best guide walkthrough get beat all
pasar conseguir encontrar derrotar build trucos todos coleccionables tier list find
collectibles 100
out your you with from into new one game games time day sin otro otra todo hacer
""".split())

# ==========================================================


def sugerencias(consulta, idioma):
    hl, gl = IDIOMAS[idioma]
    url = ("https://suggestqueries.google.com/complete/search?client=firefox"
           f"&hl={hl}&gl={gl}&q={urllib.parse.quote(consulta)}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                datos = json.loads(r.read().decode("utf-8", errors="replace"))
            time.sleep(random.uniform(*PAUSA))
            return datos[1]
        except Exception as e:
            espera = 5 * (intento + 1)
            print(f"   ! {consulta!r}: {e} — reintento en {espera}s")
            time.sleep(espera)
    return []


_PALABRAS_RUIDO = [w.replace("_", " ") for w in RUIDO.split()]
_RE_RUIDO = re.compile(r"\b(" + "|".join(re.escape(w) for w in _PALABRAS_RUIDO) + r")\b")
descartadas = []   # todo lo que el filtro quitó, para revisarlo


def es_ruido(texto):
    return _RE_RUIDO.search(texto) is not None


def recolectar(semillas, idioma, etiqueta):
    """semillas: lista de textos base. Para cada uno prueba base + a..z/0..9."""
    filas = []
    consultas = [s + l for s in semillas for l in [""] + list(LETRAS)]
    for i, q in enumerate(consultas, 1):
        if i % 25 == 0:
            print(f"   [{etiqueta} {idioma}] {i}/{len(consultas)}")
        for pos, s in enumerate(sugerencias(q, idioma), 1):
            fila = {"idioma": idioma, "consulta": q, "posicion": pos,
                    "puntos": 11 - min(pos, 10), "sugerencia": s.lower()}
            (descartadas if es_ruido(fila["sugerencia"]) else filas).append(fila)
    return filas


def guardar(nombre, filas, campos):
    CARPETA.mkdir(exist_ok=True)
    ruta = CARPETA / nombre
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
    print(f"-> {ruta} ({len(filas)} filas)")


def ranking_temas(filas):
    """Suma puntos por frase de 1 a 5 palabras (sin palabras vacías) -> juegos/temas top."""
    total = defaultdict(lambda: {"puntos": 0, "veces": 0, "es": 0, "en": 0})
    for f in filas:
        palabras = re.findall(r"[\w']+", f["sugerencia"])
        vistos = set()
        for n in (1, 2, 3, 4, 5):
            for i in range(len(palabras) - n + 1):
                trozo = palabras[i:i + n]
                if trozo[0] in VACIAS or trozo[-1] in VACIAS or len(" ".join(trozo)) < 3:
                    continue
                vistos.add(" ".join(trozo))
        for t in vistos:
            total[t]["puntos"] += f["puntos"]
            total[t]["veces"] += 1
            total[t][f["idioma"]] += f["puntos"]
    salida = [{"tema": t, **v} for t, v in total.items() if v["veces"] >= 3]
    # Frases largas primero: "elden" y "ring" se descartan si "elden ring" ya tiene casi
    # los mismos puntos (son la misma búsqueda partida en pedazos)
    salida.sort(key=lambda x: (-len(x["tema"].split()), -x["puntos"]))
    final = []
    for x in salida:
        dentro = f" {x['tema']} "
        if any(dentro in f" {k['tema']} " and k["puntos"] >= 0.9 * x["puntos"] for k in final):
            continue
        final.append(x)
    return sorted(final, key=lambda x: -x["puntos"])


def paso_descubrir():
    print("== 1. Descubrir: qué juegos aparecen en búsquedas genéricas ==")
    filas = []
    for idioma, semillas in SEMILLAS_DESCUBRIR.items():
        filas += recolectar(semillas, idioma, "descubrir")
    campos = ["idioma", "consulta", "posicion", "puntos", "sugerencia"]
    guardar("1_descubrir_sugerencias.csv", filas, campos)
    guardar("1_descubrir_descartadas.csv", descartadas, campos)
    descartadas.clear()
    guardar("1_descubrir_ranking_temas.csv", ranking_temas(filas)[:500],
            ["tema", "puntos", "veces", "es", "en"])
    print("   Abre el ranking de temas: arriba deberían salir los juegos más buscados.")


def paso_juegos():
    print("== 2. Juegos: todo lo que la gente busca de cada juego ==")
    filas = []
    for juego in JUEGOS:
        print(f" * {juego}")
        for idioma, mods in MODIFICADORES.items():
            semillas = [juego + " "] + [f"{juego} {m} " for m in mods]
            for f in recolectar(semillas, idioma, juego):
                f["juego"] = juego
                filas.append(f)
    descartadas.clear()   # aquí casi no hay ruido (todas llevan el nombre del juego)
    # Una idea por fila (sin repetir), con sus puntos sumados
    ideas = defaultdict(lambda: {"puntos": 0, "veces": 0})
    for f in filas:
        k = (f["juego"], f["idioma"], f["sugerencia"])
        ideas[k]["puntos"] += f["puntos"]
        ideas[k]["veces"] += 1
    salida = [{"juego": j, "idioma": i, "busqueda": s, **v} for (j, i, s), v in ideas.items()]
    salida.sort(key=lambda x: (x["juego"], x["idioma"], -x["puntos"]))
    guardar("2_ideas_por_juego.csv", salida, ["juego", "idioma", "busqueda", "puntos", "veces"])
    print("   Cada fila es una posible guía. Más puntos = aparece más arriba y más veces.")


def paso_trends():
    print("== 3. Google Trends: popularidad comparada (últimos 12 meses) ==")
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("   Falta pytrends. Instálalo con:  pip install pytrends")
        return
    # Trends compara máx. 5 términos a la vez: usamos un juego "ancla" en cada grupo
    # para poder poner todos en la misma escala.
    ancla = JUEGOS[0]
    resto = [j for j in JUEGOS if j != ancla]
    filas = []
    for geo, nombre in [("", "mundo"), ("MX", "mexico"), ("ES", "espana"), ("US", "eeuu")]:
        py = TrendReq(hl="es-MX", tz=360)
        valores = {}
        for i in range(0, len(resto), 4):
            grupo = [ancla] + resto[i:i + 4]
            try:
                py.build_payload(grupo, timeframe="today 12-m", geo=geo)
                df = py.interest_over_time()
            except Exception as e:
                print(f"   ! Trends falló ({nombre}): {e}. Espera unos minutos y reintenta.")
                df = None
            if df is not None and not df.empty:
                base = df[ancla].mean() or 1
                for j in grupo:
                    valores[j] = round(100 * df[j].mean() / base, 1)
            time.sleep(random.uniform(8, 15))
        for j, v in valores.items():
            filas.append({"region": nombre, "juego": j, f"popularidad_vs_{ancla}": v})
        print(f"   {nombre}: listo")
    filas.sort(key=lambda x: (x["region"], -x[f"popularidad_vs_{ancla}"]))
    guardar("3_trends_ranking.csv", filas, ["region", "juego", f"popularidad_vs_{ancla}"])
    print(f"   100 = igual de buscado que '{ancla}'; 300 = el triple.")


def menu():
    print(__doc__.split("Uso")[0].strip())
    print()
    print("  1 = descubrir    2 = juegos    3 = trends    4 = todo")
    r = input("¿Qué paso quieres correr? (1-4): ").strip().lower()
    return {"1": "descubrir", "2": "juegos", "3": "trends", "4": "todo"}.get(r, r)


if __name__ == "__main__":
    pasos = {"descubrir": [paso_descubrir], "juegos": [paso_juegos], "trends": [paso_trends],
             "todo": [paso_descubrir, paso_juegos, paso_trends]}
    # Con doble clic no hay argumentos: se muestra un menú y la ventana no se cierra sola
    doble_clic = len(sys.argv) < 2
    try:
        eleccion = sys.argv[1] if not doble_clic else menu()
        if eleccion not in pasos:
            print(f"No conozco el paso {eleccion!r}. Opciones: {', '.join(pasos)}")
        else:
            for paso in pasos[eleccion]:
                paso()
            print("\nListo. Los resultados están en:", CARPETA)
    except KeyboardInterrupt:
        print("\nCancelado.")
    except Exception:
        import traceback
        traceback.print_exc()
        print("\nAlgo falló. Copia el texto de arriba y pásaselo a Claude.")
    if doble_clic:
        input("\nPresiona Enter para cerrar...")
