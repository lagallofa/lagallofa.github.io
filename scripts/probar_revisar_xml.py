"""Pruebas de revisar_xml.py con ficheros maliciosos (deben dar error) e inofensivos (no).

Uso: python scripts/probar_revisar_xml.py   -> «Todas las pruebas pasan» o la lista de fallos
"""

import base64
import importlib.util
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("revisar_xml", Path(__file__).with_name("revisar_xml.py"))
revisar_xml = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revisar_xml)

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 16).decode()
EXE = base64.b64encode(b"MZ\x90\x00" + b"\0" * 16).decode()
SVG_MALO = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>').decode()
SVG_BUENO = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>').decode()


def pregunta(enunciado, adjuntos="", tipo="multichoice", extra="", formato_respuesta="html", respuesta="Sí"):
    return f"""<question type="{tipo}">
  <name><text>Prueba</text></name>
  <questiontext format="html"><text><![CDATA[{enunciado}]]></text>{adjuntos}</questiontext>
  <answer fraction="100" format="{formato_respuesta}"><text><![CDATA[{respuesta}]]></text></answer>
  {extra}
</question>"""


def quiz(*preguntas, cabecera=""):
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{cabecera}<quiz>\n' + "\n".join(preguntas) + "\n</quiz>\n"


def adjunto(nombre, datos):
    return f'<file name="{nombre}" path="/" encoding="base64">{datos}</file>'


# (nombre, contenido, ¿debe dar error de seguridad?)
CASOS = [
    ("XXE: entidad externa",
     quiz(pregunta("&xxe;"), cabecera='<!DOCTYPE quiz [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'), True),
    ("billion laughs",
     quiz(pregunta("&lol2;"), cabecera='<!DOCTYPE quiz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>\n'), True),
    ("etiqueta script", quiz(pregunta("<p>Hola</p><script>alert(1)</script>")), True),
    ("script en mayúsculas con espacio", quiz(pregunta("< SCRIPT >alert(1)</script>")), True),
    ("evento onerror", quiz(pregunta('<img src="x.png" onerror="alert(1)">')), True),
    ("evento con barra", quiz(pregunta('<svg/onload=alert(1)>')), True),
    ("javascript: con tabulador", quiz(pregunta('<a href="java\tscript:alert(1)">x</a>')), True),
    ("javascript: con entidades de control", quiz(pregunta('<a href=" JAVASCRIPT:alert(1)">x</a>')), True),
    ("data:text/html", quiz(pregunta('<iframe src="data:text/html,hola"></iframe>')), True),
    ("iframe", quiz(pregunta('<iframe src="https://ejemplo.org"></iframe>')), True),
    ("formulario", quiz(pregunta('<form action="https://ejemplo.org"><input name="clave"></form>')), True),
    ("meta refresh", quiz(pregunta('<meta http-equiv="refresh" content="0;url=https://ejemplo.org">')), True),
    ("estilo con expression", quiz(pregunta('<p style="width: expression(alert(1))">x</p>')), True),
    ("svg con script", quiz(pregunta('<img src="@@PLUGINFILE@@/a.svg">', adjunto("a.svg", SVG_MALO))), True),
    ("exe disfrazado de png", quiz(pregunta('<img src="@@PLUGINFILE@@/a.png">', adjunto("a.png", EXE))), True),
    ("adjunto .html", quiz(pregunta('<a href="@@PLUGINFILE@@/a.html">x</a>', adjunto("a.html", PNG))), True),
    ("respuesta HTML con script", quiz(pregunta("Bien", respuesta="<script>alert(1)</script>")), True),
    ("no es un banco de Moodle", '<?xml version="1.0"?><html><body>hola</body></html>', True),
    # Inofensivos: no deben dar error
    ("código de ejemplo escapado", quiz(pregunta("<p>¿Qué hace &lt;button onclick=&quot;f()&quot;&gt;?</p>")), False),
    ("texto plano con <script>", quiz(pregunta("¿Qué etiqueta es?", formato_respuesta="plain_text", respuesta="<script>")), False),
    ("palabra «on» en el texto", quiz(pregunta("<p>Pon el equipo on = encendido</p>")), False),
    ("svg inofensivo", quiz(pregunta('<img src="@@PLUGINFILE@@/a.svg">', adjunto("a.svg", SVG_BUENO))), False),
    ("png de verdad", quiz(pregunta('<img src="@@PLUGINFILE@@/a b.png">', adjunto("a b.png", PNG))), False),
    ("coderunner (solo aviso)",
     quiz(pregunta("Escribe un programa", tipo="coderunner", extra="<template>print(1)</template>")), False),
    ("enlace externo (solo aviso)", quiz(pregunta('<a href="https://moodle.org">Moodle</a>')), False),
]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fallos = []
    with tempfile.TemporaryDirectory() as carpeta:
        for i, (nombre, contenido, peligroso) in enumerate(CASOS):
            ruta = Path(carpeta) / f"caso{i}.xml"
            ruta.write_text(contenido, encoding="utf-8")
            res = revisar_xml.revisar_fichero(ruta)
            detectado = bool(res.errores)
            estado = "ok " if detectado == peligroso else "FALLO"
            if detectado != peligroso:
                fallos.append(nombre)
            motivo = res.errores[0].texto if res.errores else (res.hallazgos[0].texto if res.hallazgos else "sin hallazgos")
            print(f"{estado} {'peligroso ' if peligroso else 'inofensivo'} {nombre}: {motivo}")
    print("\nTodas las pruebas pasan." if not fallos else f"\nFallan {len(fallos)}: {', '.join(fallos)}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
