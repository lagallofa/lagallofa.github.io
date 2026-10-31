"""Genera indice.json con todas las actividades del repositorio.

Una actividad es:
- una carpeta con activity.json (todas las preguntas XML de esa carpeta), o
- un fichero XML suelto en una carpeta sin activity.json.

Las etiquetas se leen de activity.json:

    "curriculo": [
        { "ciclo": "DAM", "modulo": "0485", "ra": "RA3", "ce": ["a", "b", "d"] }
    ],
    "tecnologias": ["python"]

- curriculo: una tupla <ciclo, módulo, RA, CE> por módulo. Una actividad puede servir
  para varios módulos, pero dentro de un módulo solo para un RA, y sus CE son de ese RA.
  Todo tiene que existir en curriculo/ciclos.json, de donde salen los nombres.
- tecnologias: obligatoria si la actividad está clasificada; ids de
  curriculo/tecnologias.json, o "no-procede" (sola).

Si alguna actividad no cumple esto, no se genera el índice.

Uso: python scripts/generar_indice.py  (desde la raíz del repositorio)
"""

import json
import re
import shutil
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from html import escape
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Todas las actividades viven aquí; las rutas del índice son relativas a RAIZ (la web)
ACTIVIDADES = RAIZ / "actividades"
SALIDA = RAIZ / "indice.json"
# Un JSON por actividad con el texto de sus preguntas, para la página «Ver»
PREGUNTAS = RAIZ / "ver" / "datos"
MAX_IMAGENES = 6


def leer_json(ruta):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"Aviso: no se pudo leer {ruta.relative_to(RAIZ)}: {error}", file=sys.stderr)
        return {}


def nombre_carpeta(carpeta):
    nombre = carpeta.name
    return nombre[:1].upper() + nombre[1:]


def categorias(carpeta):
    """Nombres de las categorías desde la raíz hasta la carpeta (sin incluirla)."""
    nombres = []
    actual = ACTIVIDADES
    for parte in carpeta.relative_to(ACTIVIDADES).parts:
        actual = actual / parte
        info = actual / "category.json"
        if info.exists():
            nombres.append(leer_json(info).get("name") or nombre_carpeta(actual))
        else:
            nombres.append(nombre_carpeta(actual))
    return nombres


def leer_preguntas(xml):
    try:
        quiz = ET.parse(xml).getroot()
    except ET.ParseError as error:
        print(f"Aviso: XML no válido {xml.relative_to(RAIZ)}: {error}", file=sys.stderr)
        return []
    return [q for q in quiz.iter("question") if q.get("type") != "category"]


# --- Preguntas en texto para la página «Ver» -------------------------------------------
# Los XML pueden pesar decenas de MB por las imágenes incrustadas, así que la web no los lee:
# se guarda aparte el texto de cada pregunta y, si lleva imágenes, la captura de actirepo.

def slug(texto):
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-")


def capturas(xml):
    """Capturas de actirepo de cada pregunta, por nombre: «07-arrastrar-…_1.png»."""
    por_nombre = {}
    carpeta = xml.parent / "images" / xml.stem
    if carpeta.is_dir():
        for png in sorted(carpeta.glob("*.png"), key=lambda p: p.name):
            nombre, _, _ = png.stem.rpartition("_")
            por_nombre.setdefault(nombre, []).append(ruta(png))
    return por_nombre


def html(q, camino):
    return (q.findtext(camino) or "").strip()


def fraccion(el):
    try:
        return float(el.get("fraction", "0"))
    except ValueError:
        return 0.0


def respuestas(q):
    lista = []
    for a in q.findall("answer"):
        texto = (a.findtext("text") or "").strip()
        if q.get("type") == "truefalse":
            texto = {"true": "Verdadero", "false": "Falso"}.get(texto.lower(), texto)
        lista.append({
            "texto": texto,
            "fraccion": fraccion(a),
            "correcta": fraccion(a) > 0,
            "retro": html(a, "feedback/text"),
        })
    return lista


def huecos(q):
    """ddwtos y gapselect: [[n]] en el enunciado se cambia por la opción correcta n."""
    opciones = [html(o, "text") for o in q.findall("selectoption")] or \
               [html(o, "text") for o in q.findall("dragbox")]

    def poner(m):
        n = int(m.group(1)) - 1
        texto = opciones[n] if 0 <= n < len(opciones) else m.group(0)
        return f'<mark class="hueco">{escape(texto)}</mark>'
    return re.sub(r"\[\[(\d+)\]\]", poner, html(q, "questiontext/text"))


def cloze(texto):
    """Respuestas anidadas: {1:MULTICHOICE:=bien~mal} se cambia por las respuestas correctas."""
    def poner(m):
        correctas = []
        for opcion in re.split(r"(?<!\\)~", m.group(1)):
            opcion = opcion.split("#")[0]
            if opcion.startswith("="):
                correctas.append(opcion[1:])
            elif opcion.startswith("%100%"):
                correctas.append(opcion[5:])
        return f'<mark class="hueco">{escape(" / ".join(correctas) or "?")}</mark>'
    return re.sub(r"\{\d*:[A-Z_]+:([^}]*)\}", poner, texto)


def pregunta(q, capturas_xml, usadas):
    tipo = q.get("type")
    nombre = html(q, "name/text")
    datos = {
        "tipo": tipo,
        "nombre": nombre,
        "enunciado": html(q, "questiontext/text"),
        "retro": html(q, "generalfeedback/text"),
    }
    # Captura de actirepo de esta pregunta (si hay varias con el mismo nombre, por orden)
    clave = slug(nombre)
    lista = capturas_xml.get(clave, [])
    if usadas[clave] < len(lista):
        datos["captura"] = lista[usadas[clave]]
        usadas[clave] += 1

    if tipo in ("multichoice", "truefalse", "shortanswer", "numerical"):
        datos["respuestas"] = respuestas(q)
        datos["multiple"] = tipo == "multichoice" and (q.findtext("single") or "true") == "false"
    elif tipo == "matching":
        datos["pares"] = [[html(s, "text"), html(s, "answer/text")]
                          for s in q.findall("subquestion") if html(s, "text")]
    elif tipo == "ddimageortext":
        arrastres = {d.findtext("no"): html(d, "text") or "(imagen)" for d in q.findall("drag")}
        datos["pares"] = [[arrastres.get(d.findtext("choice"), "?"), f"Zona {d.findtext('no')}"]
                          for d in q.findall("drop")]
    elif tipo == "ddmarker":
        marcas = {d.findtext("no"): html(d, "text") for d in q.findall("drag")}
        datos["pares"] = [[marcas.get(d.findtext("choice"), "?"), f"Zona {d.findtext('no')}"]
                          for d in q.findall("drop")]
    elif tipo in ("ddwtos", "gapselect"):
        datos["enunciado"] = huecos(q)
    elif tipo == "multianswer":
        datos["enunciado"] = cloze(datos["enunciado"])
    elif tipo == "coderunner":
        datos["codigo"] = q.findtext("answer") or ""
        datos["pruebas"] = [[t.findtext("testcode/text") or t.findtext("stdin/text") or "",
                             t.findtext("expected/text") or ""]
                            for t in q.findall("testcases/testcase")]
    return datos


def imagenes(xml):
    carpeta = xml.parent / "images" / xml.stem
    if not carpeta.is_dir():
        return []
    return [ruta(p) for p in sorted(carpeta.glob("*.png"))[:MAX_IMAGENES]]


def ruta(p):
    return p.relative_to(RAIZ).as_posix()


def actividad(carpeta, xmls, meta):
    tipos = Counter()
    ficheros = []
    vistas = []
    textos = []
    for xml in xmls:
        preguntas = leer_preguntas(xml)
        conteo = Counter(q.get("type") for q in preguntas)
        tipos += conteo
        ficheros.append({"nombre": xml.name, "ruta": ruta(xml), "preguntas": len(preguntas)})
        vistas += imagenes(xml)
        capturas_xml, usadas = capturas(xml), Counter()
        textos += [dict(pregunta(q, capturas_xml, usadas), fichero=xml.name) for q in preguntas]

    autor = meta.get("author") or {}
    propia = (carpeta / "activity.json").exists()
    identificador = ruta(carpeta) if propia else ruta(xmls[0])
    return {
        "id": identificador,
        "textos": ruta(PREGUNTAS / f"{slug(identificador.removeprefix('actividades/'))}.json"),
        "_preguntas": textos,
        "ruta": ruta(carpeta),
        "nombre": meta.get("name") or nombre_carpeta(xmls[0].with_suffix("")),
        "descripcion": meta.get("description", ""),
        "dificultad": meta.get("difficulty", ""),
        "autor": autor.get("name", "") if isinstance(autor, dict) else str(autor),
        # La carpeta de una actividad con activity.json no es una categoría
        "categorias": categorias(carpeta.parent if propia else carpeta),
        "preguntas": sum(tipos.values()),
        "tipos": dict(tipos.most_common()),
        "ficheros": ficheros,
        "imagenes": vistas[:MAX_IMAGENES],
        "readme": ruta(carpeta / "README.md") if (carpeta / "README.md").exists() else "",
        "curriculo": meta.get("curriculo", []),
        "tecnologias": meta.get("tecnologias", []),
    }


def cargar_listas():
    """Normativa (ciclo -> módulo -> RA -> CE) y tecnologías válidas, de curriculo/."""
    ciclos = leer_json(RAIZ / "curriculo" / "ciclos.json").get("ciclos", [])
    normativa = {
        c["sigla"]: {
            "nombre": c["nombre"], "nivel": c["nivel"],
            "modulos": {m["codigo"]: {"nombre": m["nombre"],
                                      "ra": {r["ra"]: {x["ce"] for x in r["ce"]} for r in m["ra"]}}
                        for m in c["modulos"]},
        }
        for c in ciclos
    }
    lista = leer_json(RAIZ / "curriculo" / "tecnologias.json")
    tecnologias = {t["id"]: t["nombre"] for t in lista.get("especiales", [])} | \
                  {t["id"]: t["nombre"] for g in lista.get("grupos", []) for t in g["tecnologias"]}
    temas = {t["id"]: {"nombre": t["nombre"], "subtemas": {s["id"]: s["nombre"] for s in t["subtemas"]}}
             for t in leer_json(RAIZ / "curriculo" / "temas.json").get("temas", [])}
    return normativa, tecnologias, temas


def tema_de(act, temas):
    """Tema y subtema según la carpeta: actividades/<tema>/<subtema>/<actividad>."""
    partes = Path(act["ruta"]).relative_to("actividades").parts
    if len(partes) != 3 or partes[0] not in temas or partes[1] not in temas[partes[0]]["subtemas"]:
        return None
    tema = temas[partes[0]]
    return {"tema": partes[0], "tema_nombre": tema["nombre"],
            "subtema": partes[1], "subtema_nombre": tema["subtemas"][partes[1]]}


def validar(act, normativa, tecnologias, temas):
    """Errores de las etiquetas de una actividad."""
    errores = []
    if not tema_de(act, temas):
        errores.append("tiene que estar en actividades/<tema>/<subtema>/<carpeta de la actividad>/, "
                       "con un tema y subtema de curriculo/temas.json")
    modulos = {}
    for i, t in enumerate(act["curriculo"], 1):
        faltan = [c for c in ("ciclo", "modulo", "ra", "ce") if not t.get(c)]
        if faltan:
            errores.append(f"tupla {i}: falta {', '.join(faltan)}")
            continue
        ciclo = normativa.get(t["ciclo"])
        modulo = ciclo and ciclo["modulos"].get(t["modulo"])
        ces = modulo and modulo["ra"].get(t["ra"])
        if not ciclo:
            errores.append(f"tupla {i}: el ciclo «{t['ciclo']}» no existe ({', '.join(normativa)})")
        elif not modulo:
            errores.append(f"tupla {i}: el módulo {t['modulo']} no es de {t['ciclo']}")
        elif ces is None:
            errores.append(f"tupla {i}: el módulo {t['modulo']} de {t['ciclo']} no tiene {t['ra']}")
        elif sobran := [c for c in t["ce"] if c not in ces]:
            errores.append(f"tupla {i}: {t['ra']} de {t['modulo']} ({t['ciclo']}) no tiene los CE {', '.join(sobran)}")
        clave = (t["ciclo"], t["modulo"])
        if clave in modulos and modulos[clave] != t["ra"]:
            errores.append(f"el módulo {t['modulo']} de {t['ciclo']} aparece con {modulos[clave]} y con "
                           f"{t['ra']}: dentro de un módulo solo puede haber un RA")
        modulos.setdefault(clave, t["ra"])

    tec = act["tecnologias"]
    if act["curriculo"] and not tec:
        errores.append('falta "tecnologias" (una de la lista o "no-procede")')
    if desconocidas := [x for x in tec if x not in tecnologias]:
        errores.append(f"tecnologías que no están en la lista: {', '.join(desconocidas)}")
    if "no-procede" in tec and len(tec) > 1:
        errores.append('"no-procede" no se puede combinar con otras tecnologías')
    return errores


def nombrar(act, normativa):
    """Añade a cada tupla los nombres de nivel, ciclo y módulo, para el buscador."""
    for t in act["curriculo"]:
        ciclo = normativa[t["ciclo"]]
        t.update(sigla=t["ciclo"], nivel=ciclo["nivel"], ciclo=ciclo["nombre"], codigo=t["modulo"],
                 modulo=f"{t['modulo']} {ciclo['modulos'][t['modulo']]['nombre']}")


def recorrer(carpeta, salida):
    if carpeta.name == "images":
        return
    xmls = sorted(carpeta.glob("*.xml"))
    meta_ruta = carpeta / "activity.json"
    if xmls and meta_ruta.exists():
        salida.append(actividad(carpeta, xmls, leer_json(meta_ruta)))
    else:
        for xml in xmls:
            salida.append(actividad(carpeta, [xml], {}))
    for hija in sorted(p for p in carpeta.iterdir() if p.is_dir()):
        recorrer(hija, salida)


def main():
    actividades = []
    for hija in sorted(p for p in ACTIVIDADES.iterdir() if p.is_dir()):
        recorrer(hija, actividades)

    normativa, tecnologias, temas = cargar_listas()
    errores = [(a["id"], e) for a in actividades for e in validar(a, normativa, tecnologias, temas)]
    if errores:
        for actividad_id, error in errores:
            print(f"Error en {actividad_id}: {error}", file=sys.stderr)
        sys.exit(f"No se ha generado {SALIDA.name}: corrige los errores de clasificación.")
    for act in actividades:
        nombrar(act, normativa)
        act.update(tema_de(act, temas))

    # Preguntas en texto: se rehacen todas para no dejar ficheros de actividades borradas
    shutil.rmtree(PREGUNTAS, ignore_errors=True)
    PREGUNTAS.mkdir(parents=True)
    for act in actividades:
        datos = {"id": act["id"], "preguntas": act.pop("_preguntas")}
        (RAIZ / act["textos"]).write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    repo = leer_json(ACTIVIDADES / "repo.json") if (ACTIVIDADES / "repo.json").exists() else {}
    # Nombres de las tecnologías usadas, para los filtros del buscador
    usadas = {t for a in actividades for t in a["tecnologias"]}
    indice = {"repositorio": repo, "tecnologias": {t: n for t, n in tecnologias.items() if t in usadas},
              "actividades": actividades}
    texto = json.dumps(indice, ensure_ascii=False, indent=1)
    SALIDA.write_text(texto + "\n", encoding="utf-8")
    # Copia como script para que el buscador funcione también abierto como archivo (file://),
    # donde el navegador no deja leer indice.json
    SALIDA.with_suffix(".js").write_text(f"window.INDICE = {texto};\n", encoding="utf-8")

    clasificadas = sum(1 for a in actividades if a["curriculo"])
    print(f"{len(actividades)} actividades ({clasificadas} clasificadas) -> {SALIDA.name}")


if __name__ == "__main__":
    main()
