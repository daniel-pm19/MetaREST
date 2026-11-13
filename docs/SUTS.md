# APIs bajo prueba (SUTs)

| # | SUT | Para qué sirve en los experimentos |
|---|---|---|
| 1 | API demo propia (`sut-demo/`) con fallos inyectables | RQ1–RQ4; RQ3 (detección de fallos) solo se mide aquí |
| 2 | **PokeAPI** (`https://pokeapi.co`) | RQ1, RQ2, RQ4 y cobertura, sobre datos estáticos |
| 3 | **Crossref REST API** (`https://api.crossref.org`) | RQ1, RQ2, RQ4 y cobertura, sobre datos reales con búsqueda y filtros |

Specs curados, cambios y configuración de cada SUT: [`experiments/specs/`](../experiments/specs/README.md).
Elegidas por Daniel el 13-nov-2026.

## Criterios

1. OpenAPI oficial descargable, con esquemas de respuesta (sin ellos el LLM no tiene campos para los selectores).
2. Operaciones GET con búsqueda, filtros, orden o paginación (donde hay relaciones metamórficas interesantes).
3. Sin autenticación o con key gratuita.
4. Rate limit tolerable para unas decenas de runs.
5. Que, entre las dos, cubran casos distintos.

## Por qué estas dos

| | PokeAPI | Crossref |
|---|---|---|
| Spec | OpenAPI 3.1, 102 operaciones GET (15 tras curar), todas con esquema de respuesta | Swagger 2.0, 18 operaciones GET, todas con esquema |
| Qué ejercita | Paginación `limit`/`offset`, detalle por id o nombre, `count` | Búsqueda `query`, `filter`, `sort`/`order`, paginación `rows`/`offset` |
| Datos | Estáticos y deterministas | Reales y vivos (> 1M trabajos), cambian despacio |
| Límites | Sin auth ni rate limit; caché de 24 h | Sin auth; 1 req/s y 1 conexión en el pool público |
| Latencia | ~70–300 ms | ~2–4 s |

Se complementan: OpenAPI 3.1 frente a Swagger 2.0 (prueban las dos ramas del extractor), datos estáticos
frente a vivos, y paginación frente a búsqueda con filtros.

**Verificado en vivo** (13-nov-2026):
- PokeAPI: dos páginas de 10 son exactamente una de 20; `/pokemon/25/` y `/pokemon/pikachu/` son iguales; un
  `limit` enorme devuelve las 1351 entradas; HEAD responde 200. Una MR `complete` de paginación da `pass`.
- Crossref: con `sort` fijo, la página 2 de 10 es la segunda mitad de una de 20; agregar un filtro reduce
  `total-results`. Una MR `count_leq` sobre filtros (con `append_to_param` y separador `,`) da `pass`.

## Riesgos conocidos

- **Crossref ordena por relevancia de forma no determinista**: la misma búsqueda repetida devolvió otro orden.
  Una MR de `equality` o de paginación sin `sort` explícito daría violaciones falsas. El prompt ya pide fijar el
  orden; además es un buen caso para medir si el filtro semántico lo detecta (RQ1). En el etiquetado manual,
  una violación de este tipo cuenta como MR inválida, no como fallo de Crossref.
- **Crossref crece con el tiempo**: los totales cambian entre días, no dentro de un run (la ejecución dura
  minutos). Ejecutar cada run de una vez.
- **Crossref es lento con 1 req/s**: 20 MRs con 2–3 instancias y 2–3 peticiones cada una son unas 150
  peticiones, del orden de 5–10 minutos por run.
- **Polite pool**: con un correo en `mailto` Crossref da más cuota. No se usa: sería un dato personal. Si hiciera
  falta, se decide en equipo qué correo institucional usar.

## Descartadas

| API | Motivo |
|---|---|
| Art Institute of Chicago | El OpenAPI no tiene esquemas de respuesta |
| iNaturalist | Spec de ~64k tokens, la mitad de las operaciones con auth y datos que cambian cada minuto |
| JSONPlaceholder, REST Countries | Sin OpenAPI oficial: escribirlo nosotros sesgaría los experimentos |
| Open Library | No se encontró un OpenAPI oficial descargable; su API de búsqueda está marcada como experimental |

## Limitación del contrato de MR a mencionar en el paper

Los follow-ups se derivan de los **parámetros** de la fuente, no de su **respuesta**. No se pueden expresar
relaciones encadenadas como «los pokémon que lista `/type/fire` tienen el tipo fire en `/pokemon/{id}`».
