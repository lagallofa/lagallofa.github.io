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
| [`scripts/`](scripts) | Programas que generan el índice |

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
