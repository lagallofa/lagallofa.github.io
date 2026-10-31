# La Gallofa

Actividades de FP de Informática para Moodle (formato Moodle XML), compartidas entre
profesorado y organizadas por nivel, ciclo, módulo, resultado de aprendizaje (RA) y criterio
de evaluación (CE).

**Web: <https://lagallofa.github.io>**

> En Canarias, en la isla de La Palma, una gallofa era una reunión de vecinos para ayudar a uno
> de ellos en la realización de una determinada faena. La persona beneficiada obsequiaba a los
> demás con comida y bebida.

## Qué hay en este repositorio

| Carpeta o fichero | Qué es |
|---|---|
| [`index.html`](index.html) | Página de inicio de la web |
| [`buscar/`](buscar) | Buscador de actividades |
| [`aportar/`](aportar), [`modificar/`](modificar), [`retirar/`](retirar) | Páginas para que el profesorado gestione sus actividades |
| [`actividades/`](actividades) | Las actividades: una carpeta por actividad, con su XML, capturas y ficha `activity.json` |
| `indice.json`, `indice.js` | Lista de todas las actividades para el buscador (se genera sola) |
| [`scripts/`](scripts) | Programas: índice del buscador (`generar_indice.py`), revisión de seguridad y calidad de los XML (`revisar_xml.py`, con sus pruebas en `probar_revisar_xml.py`) y limpieza de adjuntos sobrantes (`limpiar_xml.py`) |

## Ficha de una actividad (`activity.json`)

```json
{
  "name": "Tipos de apantallamiento",
  "description": "Preguntas de opción múltiple y de arrastrar y soltar marcadores",
  "difficulty": "easy",
  "author": { "name": "Noemí Pérez" },
  "curriculo": [
    {
      "nivel": "Grado Medio",
      "ciclo": "Sistemas Microinformáticos y Redes",
      "modulo": "Redes locales",
      "ra": "RA1",
      "ce": ["a", "b"]
    }
  ]
}
```

Una actividad puede servir para varios módulos (una entrada por módulo), pero dentro de un
módulo solo para un RA, y sus CE son de ese RA.

Las páginas de cada actividad las genera [actirepo](https://github.com/teuton-software/actirepo)
automáticamente en cada cambio.

## Seguridad de los XML

Antes de publicar, cada fichero se revisa con `scripts/revisar_xml.py`: que no declare entidades XML (ataques XXE), que su HTML no lleve código (scripts, eventos, enlaces `javascript:`, iframes, formularios…) y que los adjuntos sean imágenes, audio, vídeo o PDF de verdad, no ficheros disfrazados ni SVG con código. Las preguntas que ejecutan código (CodeRunner, STACK) se marcan para revisarlas a mano. Si hay un problema de seguridad, la actualización automática se detiene y las aportaciones salen en rojo.
