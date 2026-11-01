"""Revisa ficheros Moodle XML antes de publicarlos en La Gallofa.

Dos cosas:

1. Seguridad: que el fichero no pueda hacer daño a quien lo importe en su Moodle ni a quien lo vea
   en la web. Busca entidades XML (ataques XXE y «billion laughs»), HTML con código (scripts,
   eventos, enlaces javascript:, iframes, formularios…), adjuntos peligrosos o disfrazados
   (un .exe llamado .png, SVG con código) y tipos de pregunta que ejecutan código (CodeRunner,
   STACK), que hay que revisar a mano.
2. Calidad: un resumen de cada pregunta (tipo, respuestas, puntuación, imágenes) para revisarla,
   más avisos de limpieza: adjuntos que no se usan, imágenes que faltan, nombres repetidos,
   correos electrónicos (datos personales), enlaces externos.

Los problemas de seguridad son «errores»: el programa termina con código 1 y el fichero no debe
publicarse. Lo demás son «avisos».

Uso:
    python scripts/revisar_xml.py actividades                 # todos los XML de la carpeta
    python scripts/revisar_xml.py fichero.xml --preguntas     # con el detalle de cada pregunta
    python scripts/revisar_xml.py actividades --salida informe.md
"""

import argparse
import base64
import binascii
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

ERROR, AVISO = "error", "aviso"

TIPOS_CONOCIDOS = {
    "multichoice", "truefalse", "shortanswer", "numerical", "matching", "essay", "description",
    "ddimageortext", "ddmarker", "ddwtos", "gapselect", "multianswer", "cloze", "calculated",
    "calculatedsimple", "calculatedmulti", "randomsamatch", "ordering", "coderunner", "stack",
}
# Tipos cuyo contenido se ejecuta (en el servidor de Moodle o en un servidor de pruebas)
TIPOS_CON_CODIGO = {"coderunner", "stack"}

# Adjuntos permitidos y cómo empiezan sus bytes (para detectar ficheros disfrazados)
FIRMAS = {
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".jfif": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"],
    ".webp": [b"RIFF"],
    ".pdf": [b"%PDF"],
    ".mp3": [b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"],
    ".ogg": [b"OggS"],
    ".mp4": [],  # la firma va en el byte 4 («ftyp»); se comprueba aparte
    ".svg": [],  # es texto: se revisa su contenido
}
TAMANO_MAXIMO = 20 * 1024 * 1024  # 20 MB
# Bloques que Moodle trata como HTML aunque el fichero no diga su formato
HTML_POR_DEFECTO = {"questiontext", "generalfeedback", "correctfeedback", "partiallycorrectfeedback",
                    "incorrectfeedback", "feedback", "answer", "subquestion"}

ETIQUETA_PELIGROSA = re.compile(
    r"<\s*(script|iframe|frame|frameset|object|embed|applet|form|meta|base|link)\b", re.IGNORECASE)
# Solo cuenta lo que está dentro de una etiqueta real: el código que una pregunta enseña como
# ejemplo va escapado (&lt;button onclick=…&gt;) y no se ejecuta
ETIQUETA = re.compile(r"<[a-zA-Z][^>]*>")
EVENTO = re.compile(r"[\s\"'/]on[a-z]+\s*=", re.IGNORECASE)
ATRIBUTO_DIRECCION = re.compile(
    r"\b(?:href|src|action|formaction|data|background|poster|xlink:href)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
ESQUEMA_PELIGROSO = re.compile(r"^(javascript|vbscript|data:text/html|data:image/svg)", re.IGNORECASE)
ESTILO_PELIGROSO = re.compile(r"expression\s*\(|url\s*\(\s*['\"]?\s*javascript:|-moz-binding|behavior\s*:", re.IGNORECASE)
CORREO = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# El nombre puede llevar espacios sin codificar («image (1).png»): llega hasta la comilla
REFERENCIA = re.compile(r"@@PLUGINFILE@@/([^\"'?#<>]+)")
CONTROL = re.compile(r"[\s\x00-\x1f]")


@dataclass
class Hallazgo:
    nivel: str
    donde: str
    texto: str


@dataclass
class Resultado:
    fichero: Path
    hallazgos: list = field(default_factory=list)
    preguntas: list = field(default_factory=list)

    def anotar(self, nivel, donde, texto):
        self.hallazgos.append(Hallazgo(nivel, donde, texto))

    @property
    def errores(self):
        return [h for h in self.hallazgos if h.nivel == ERROR]


def revisar_html(res, donde, html):
    """Código o enlaces peligrosos dentro del HTML de una pregunta."""
    if not html:
        return
    if m := ETIQUETA_PELIGROSA.search(html):
        res.anotar(ERROR, donde, f"etiqueta peligrosa <{m.group(1).lower()}>")
    if re.search(r"<\s*style\b", html, re.IGNORECASE):
        res.anotar(AVISO, donde, "hoja de estilos <style> incrustada: puede cambiar el aspecto de Moodle")
    etiquetas = " ".join(ETIQUETA.findall(html))
    if EVENTO.search(etiquetas):
        res.anotar(ERROR, donde, "código en un atributo de evento (onclick, onerror…)")
    if ESTILO_PELIGROSO.search(etiquetas) or ESTILO_PELIGROSO.search(" ".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.IGNORECASE | re.DOTALL))):
        res.anotar(ERROR, donde, "estilo con código (expression, javascript:…)")
    for valor in ATRIBUTO_DIRECCION.findall(etiquetas):
        limpio = CONTROL.sub("", valor.strip("\"'"))
        if ESQUEMA_PELIGROSO.match(limpio):
            res.anotar(ERROR, donde, f"enlace o recurso con código: {limpio[:40]}")
        elif limpio.lower().startswith(("http://", "https://", "//")):
            res.anotar(AVISO, donde, f"enlace o imagen externa: {urlparse(limpio).netloc or limpio[:40]}")
    for correo in set(CORREO.findall(html)):
        res.anotar(AVISO, donde, f"correo electrónico (¿dato personal?): {correo}")


def revisar_adjunto(res, donde, adjunto):
    """Un <file> incrustado: que sea de un tipo permitido y sea lo que dice ser."""
    nombre = adjunto.get("name", "")
    extension = Path(nombre).suffix.lower()
    try:
        datos = base64.b64decode(adjunto.text or "", validate=False)
    except (binascii.Error, ValueError):
        res.anotar(ERROR, donde, f"adjunto dañado (base64 incorrecto): {nombre}")
        return 0
    if extension not in FIRMAS:
        res.anotar(ERROR, donde, f"adjunto de un tipo no permitido: {nombre}")
        return len(datos)
    if extension == ".svg":
        texto = datos.decode("utf-8", "replace")
        if re.search(r"<\s*script|<\s*foreignObject|javascript:", texto, re.IGNORECASE) or EVENTO.search(texto):
            res.anotar(ERROR, donde, f"imagen SVG con código: {nombre}")
    elif extension == ".mp4":
        if datos[4:8] != b"ftyp":
            res.anotar(ERROR, donde, f"el adjunto no es lo que dice ser ({extension}): {nombre}")
    elif not any(datos.startswith(f) for f in FIRMAS[extension]):
        res.anotar(ERROR, donde, f"el adjunto no es lo que dice ser ({extension}): {nombre}")
    return len(datos)


def nombre_pregunta(q, n):
    return f"pregunta {n} «{(q.findtext('name/text') or '').strip()[:50]}»"


def revisar_pregunta(res, q, n):
    tipo = q.get("type", "")
    donde = nombre_pregunta(q, n)
    if tipo not in TIPOS_CONOCIDOS:
        res.anotar(AVISO, donde, f"tipo de pregunta desconocido: {tipo}")
    if tipo in TIPOS_CON_CODIGO:
        extra = " con plantilla propia" if (q.findtext("template") or "").strip() else ""
        res.anotar(AVISO, donde, f"pregunta {tipo}{extra}: ejecuta código; revisarla a mano")

    # Todo el HTML de la pregunta (enunciado, respuestas, retroalimentación…). Los campos de
    # texto plano o Markdown no se revisan como HTML: Moodle los escapa al mostrarlos
    for bloque in q.iter():
        texto = bloque.find("text")
        formato = bloque.get("format")
        es_html = formato in ("html", "moodle_auto_format") or (formato is None and bloque.tag in HTML_POR_DEFECTO)
        if texto is not None and es_html:
            revisar_html(res, donde, texto.text)

    # Adjuntos: comprobarlos y ver si el texto de su bloque los usa
    tamano = 0
    imagenes = 0
    for bloque in q.iter():
        adjuntos = bloque.findall("file")
        if not adjuntos:
            continue
        texto = unquote(bloque.findtext("text") or "")
        usados = {unquote(r) for r in REFERENCIA.findall(texto)}
        for adjunto in adjuntos:
            tamano += revisar_adjunto(res, donde, adjunto)
            # Los adjuntos sueltos en la pregunta o en un <drag> son fondos e imágenes de arrastrar
            if bloque is q or bloque.tag in ("drag", "dragbox") or adjunto.get("name") in usados:
                imagenes += 1
            else:
                res.anotar(AVISO, donde, f"adjunto que no se muestra: {adjunto.get('name')} (se puede limpiar)")
        for falta in usados - {a.get("name") for a in adjuntos}:
            res.anotar(AVISO, donde, f"muestra una imagen que no está en el fichero: {falta}")

    respuestas = q.findall("answer")
    correctas = [a for a in respuestas if float(a.get("fraction", "0") or 0) > 0]
    shuffle = q.find("shuffleanswers")
    res.preguntas.append({
        "n": n,
        "tipo": tipo,
        "nombre": (q.findtext("name/text") or "").strip(),
        "respuestas": len(respuestas) or len(q.findall("subquestion")) or len(q.findall("drop")),
        "correctas": len(correctas),
        "imagenes": imagenes,
        "nota": (q.findtext("defaultgrade") or "").strip(),
        "penalizacion": (q.findtext("penalty") or "").strip(),
        "barajar": "—" if shuffle is None else ("sí" if (shuffle.text or "true").strip() in ("", "1", "true") else "no"),
        "enunciado": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", q.findtext("questiontext/text") or "")).strip(),
        "textos_respuestas": [(re.sub(r"<[^>]+>", "", a.findtext("text") or "").strip(),
                               float(a.get("fraction", "0") or 0)) for a in respuestas],
    })
    return tamano


def revisar_fichero(ruta):
    res = Resultado(ruta)
    crudo = ruta.read_bytes()
    # Las entidades XML permiten leer ficheros del servidor (XXE) o colgarlo («billion laughs»).
    # Moodle no las necesita: si aparecen, no se analiza más.
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", crudo, re.IGNORECASE):
        res.anotar(ERROR, "fichero", "declara DOCTYPE o ENTITY (posible ataque XXE); no se analiza")
        return res
    if len(crudo) > TAMANO_MAXIMO:
        res.anotar(AVISO, "fichero", f"pesa {len(crudo) / 1e6:.1f} MB; conviene quitar adjuntos sobrantes")
    try:
        raiz = ET.fromstring(crudo)
    except ET.ParseError as error:
        res.anotar(ERROR, "fichero", f"no es un XML válido: {error}")
        return res
    if raiz.tag != "quiz":
        res.anotar(ERROR, "fichero", f"no es un fichero de preguntas de Moodle (raíz <{raiz.tag}>)")
        return res

    nombres = Counter()
    n = 0
    for q in raiz.iter("question"):
        if q.get("type") == "category":
            categoria = (q.findtext("category/text") or "").strip()
            if categoria.startswith("$system$"):
                res.anotar(AVISO, "categoría", f"se importaría en el contexto del sistema: {categoria}")
            continue
        n += 1
        revisar_pregunta(res, q, n)
        nombres[(q.findtext("name/text") or "").strip()] += 1
    for nombre, veces in nombres.items():
        if veces > 1:
            res.anotar(AVISO, "nombres", f"{veces} preguntas se llaman igual: «{nombre}»")
    if n == 0:
        res.anotar(AVISO, "fichero", "no tiene preguntas")
    return res


def informe(resultados, detalle):
    lineas = ["# Revisión de ficheros Moodle XML", ""]
    total_errores = sum(len(r.errores) for r in resultados)
    lineas.append(f"**{len(resultados)} ficheros · {total_errores} problemas de seguridad · "
                  f"{sum(len(r.hallazgos) for r in resultados) - total_errores} avisos**")
    for r in resultados:
        estado = "❌ NO PUBLICAR" if r.errores else "✅ seguro"
        lineas += ["", f"## {r.fichero.as_posix()} — {estado} · {len(r.preguntas)} preguntas"]
        agrupados = Counter((h.nivel, h.texto.split(":")[0]) for h in r.hallazgos)
        for nivel, titulo in (ERROR, "Problemas de seguridad"), (AVISO, "Avisos"):
            propios = [h for h in r.hallazgos if h.nivel == nivel]
            if not propios:
                continue
            lineas += ["", f"**{titulo}:**", ""]
            if nivel == AVISO and not detalle and len(propios) > 8:
                lineas += [f"- {veces} × {texto}" for (niv, texto), veces in agrupados.items() if niv == AVISO]
            else:
                lineas += [f"- {h.donde}: {h.texto}" for h in propios]
        if r.preguntas:
            lineas += ["", "| N.º | Tipo | Nombre | Resp. | Correctas | Imágenes | Nota | Penaliz. | Barajar |",
                       "|---|---|---|---|---|---|---|---|---|"]
            for p in r.preguntas:
                lineas.append(f"| {p['n']} | {p['tipo']} | {p['nombre'][:45]} | {p['respuestas']} | "
                              f"{p['correctas']} | {p['imagenes']} | {p['nota'][:4]} | {p['penalizacion'][:5]} | {p['barajar']} |")
        if detalle:
            for p in r.preguntas:
                lineas += ["", f"### {p['n']}. {p['nombre']} ({p['tipo']})", "", p["enunciado"][:600]]
                lineas += [f"- {'✔' if f > 0 else '·'} {t[:120]} ({f:g})" for t, f in p["textos_respuestas"]]
    return "\n".join(lineas) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Revisa ficheros Moodle XML (seguridad y calidad).")
    parser.add_argument("rutas", nargs="+", type=Path, help="ficheros .xml o carpetas")
    parser.add_argument("--preguntas", action="store_true", help="incluye el texto de cada pregunta")
    parser.add_argument("--salida", type=Path, help="añade el informe a este fichero (Markdown)")
    args = parser.parse_args()

    ficheros = sorted({f for r in args.rutas for f in ([r] if r.is_file() else r.rglob("*.xml"))})
    resultados = [revisar_fichero(f) for f in ficheros]
    texto = informe(resultados, args.preguntas)
    if args.salida:
        with args.salida.open("a", encoding="utf-8") as salida:
            salida.write(texto)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(texto)
    sys.exit(1 if any(r.errores for r in resultados) else 0)


if __name__ == "__main__":
    main()
