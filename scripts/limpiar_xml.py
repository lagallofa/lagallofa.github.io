"""Quita de un fichero Moodle XML los adjuntos que ninguna pregunta muestra.

Al duplicar preguntas en Moodle, cada copia arrastra las imágenes de la original aunque ya no las
use, y el fichero crece sin motivo. Este programa:

1. Quita cada <file> de un bloque (enunciado, retroalimentación…) cuyo texto no lo muestra.
   No toca los adjuntos sueltos de la pregunta ni los de <drag> (fondos e imágenes de arrastrar).
2. Comprueba que, quitando los adjuntos, el fichero nuevo es idéntico al original elemento a
   elemento y que no queda ninguna imagen mostrada sin su fichero. Si algo no cuadra, no guarda.
3. Guarda una copia del original con la extensión .xml.orig (salvo con --sin-copia).

Edita el texto del fichero sin reescribirlo entero, para conservar el formato de Moodle (CDATA,
sangrías…).

Uso: python scripts/limpiar_xml.py fichero.xml [--simular] [--sin-copia]
"""

import argparse
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

BLOQUE = re.compile(
    r"<(questiontext|generalfeedback|correctfeedback|partiallycorrectfeedback|incorrectfeedback|feedback)"
    r"(\s[^>]*)?>(.*?)</\1>", re.DOTALL)
ADJUNTO = re.compile(r"\s*<file name=\"([^\"]*)\"[^>]*>[^<]*</file>")
# El nombre puede llevar espacios sin codificar («image (1).png»): llega hasta la comilla
REFERENCIA = re.compile(r"@@PLUGINFILE@@/([^\"'?#<>]+)")


def limpiar(texto):
    """Devuelve el texto sin los adjuntos que no se muestran y la lista de los quitados."""
    quitados = []

    def bloque(m):
        contenido = m.group(3)
        interior = re.search(r"<text>(.*?)</text>", contenido, re.DOTALL)
        usados = {unquote(r) for r in REFERENCIA.findall(interior.group(1) if interior else "")}

        def adjunto(a):
            if unquote(a.group(1)) in usados or a.group(1) in usados:
                return a.group(0)
            quitados.append(a.group(1))
            return ""
        inicio = m.start(3) - m.start(0)
        return m.group(0)[:inicio] + ADJUNTO.sub(adjunto, contenido) + m.group(0)[inicio + len(contenido):]

    return BLOQUE.sub(bloque, texto), quitados


def firma(el):
    """El árbol sin adjuntos: etiqueta, atributos y texto de cada elemento."""
    return (el.tag, tuple(sorted(el.attrib.items())), (el.text or "").strip(),
            tuple(firma(h) for h in el if h.tag != "file"))


def comprobar(original, nuevo):
    """Errores si el fichero limpio no es el original sin adjuntos sobrantes."""
    errores = []
    a, b = ET.fromstring(original), ET.fromstring(nuevo)
    if firma(a) != firma(b):
        errores.append("el contenido de las preguntas ha cambiado")
    for el in b.iter():
        nombres = {f.get("name") for f in el.findall("file")}
        texto = unquote(el.findtext("text") or "")
        for ref in REFERENCIA.findall(texto):
            if unquote(ref) not in nombres and el.tag != "question":
                errores.append(f"falta el fichero de una imagen mostrada: {unquote(ref)}")
    return errores


def main():
    parser = argparse.ArgumentParser(description="Quita adjuntos sobrantes de un Moodle XML.")
    parser.add_argument("fichero", type=Path)
    parser.add_argument("--simular", action="store_true", help="dice qué quitaría, sin guardar")
    parser.add_argument("--sin-copia", action="store_true", help="no guarda el .xml.orig")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    original = args.fichero.read_text(encoding="utf-8")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", original, re.IGNORECASE):
        sys.exit("El fichero declara DOCTYPE o ENTITY: revísalo con revisar_xml.py antes de limpiarlo.")
    nuevo, quitados = limpiar(original)
    if not quitados:
        print("No hay adjuntos sobrantes.")
        return
    if errores := comprobar(original, nuevo):
        sys.exit("No se guarda nada:\n  " + "\n  ".join(errores))

    print(f"{len(quitados)} adjuntos sin usar · {len(original) / 1e6:.1f} MB -> {len(nuevo) / 1e6:.1f} MB")
    if args.simular:
        print("(simulación: no se ha guardado nada)")
        return
    if not args.sin_copia:
        shutil.copyfile(args.fichero, args.fichero.with_name(args.fichero.name + ".orig"))
    args.fichero.write_text(nuevo, encoding="utf-8", newline="\n")
    print("Guardado. Comprobado: las preguntas son las mismas y no falta ninguna imagen.")


if __name__ == "__main__":
    main()
