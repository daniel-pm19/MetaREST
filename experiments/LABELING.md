# Guía de etiquetado (RQ1)

Hojas: `results/pokeapi_labels.csv` y `results/crossref_labels.csv` (20 MRs cada una, las de `run1`). Ábrelas en
LibreOffice Calc o Excel (codificación **UTF-8**, separador **coma**). Cuenta con unos 30–40 min por hoja.

## Reglas del proceso

1. Cada etiquetador trabaja en **su propio archivo** y llena **solo su columna**:
   - A → `label_a` en `results/<api>_labels.csv`;
   - B → `label_b` en una copia en blanco de esa hoja, guardada como `results/<api>_labels_b.csv`.

   No se habla de las MRs ni se abre el archivo del otro hasta que los dos terminen.
2. Valores: `1` = válida, `0` = inválida. Nada más en esa columna. Si dudas, decide igual y explica en `notes`.
3. **No ejecutes las MRs ni mires los resultados de MetaREST** (UI, `raw/`, CSV de detecciones). Sí puedes abrir el
   OpenAPI (`specs/`) y, para comprobar un **dato** (p. ej. qué tipo es el id 10), abrir una URL de la API; pero no
   etiquetes según si la relación se cumplió en esa respuesta, sino según si **debe** cumplirse.
4. **Sin IA**: la etiqueta es el criterio de la persona (es lo que mide RQ1).
5. Al terminar los dos, se juntan las columnas (ver al final) y solo donde difieren se discute y se escribe el valor
   acordado en `label_final`.

## Qué es una MR válida

Las **dos** condiciones:

- **(a) La relación debe cumplirse siempre en una implementación correcta de la API**, según lo que documenta el
  OpenAPI (y convenciones REST razonables cuando el spec no dice nada).
- **(b) Se puede ejecutar tal como está**: el endpoint y los parámetros existen en esa operación, los valores tienen
  sentido para ese parámetro y los selectores apuntan a campos reales de la respuesta.

Si la API real falla una MR correcta, la MR **sigue siendo válida** (eso es justamente encontrar un fallo).

## Cómo leer una fila (30 segundos)

1. `operation`, `source_requests`, `followup_requests`: qué se pide primero y qué se pide después.
2. `relation` + `source_selector` / `followup_selector`: qué se compara. Significado de cada relación:

| `relation` | Qué afirma (S = fuente, F = follow-ups) |
|---|---|
| `equality` | lo seleccionado en S y en cada F es idéntico y en el mismo orden |
| `equivalence` | mismos elementos, el orden no importa |
| `subset` | `followup_in_source`: F ⊆ S · `source_in_followup`: S ⊆ F |
| `disjoint` | S y todos los F no comparten ningún elemento entre sí (todos contra todos) |
| `complete` | la unión de los F es exactamente S |
| `difference` | S menos F1 es igual a F2 |
| `count_leq` | `followup_in_source`: medida(F) ≤ medida(S) · `source_in_followup`: medida(S) ≤ medida(F); `measure=count` cuenta elementos, `measure=value` compara el número seleccionado |
| `same_order` | los elementos comunes aparecen en el mismo orden relativo |

3. Pregúntate: *si la API estuviera bien hecha, ¿esto se cumple para estas peticiones, siempre?* Si sí y (b) se
   cumple → `1`. Si no, o si depende de la suerte → `0`.
4. `title`, `description`, `rationale` ayudan a entender la intención, pero **manda lo que dicen las peticiones y la
   relación**: si el texto promete algo y el JSON hace otra cosa, se juzga el JSON.

## Lista de chequeo rápida

- [ ] ¿El parámetro existe **en esa operación** del spec? (no en otra parecida)
- [ ] ¿El valor es aceptable? (ids que existen, enums válidos, filtros soportados por **ese** endpoint)
- [ ] ¿El selector apunta a un campo que existe y es lo que se quiere comparar? (lista de elementos vs. un número)
- [ ] ¿La dirección (`followup_in_source` / `source_in_followup`) es la correcta, no la contraria?
- [ ] ¿La relación depende de algo no determinista (muestras aleatorias, orden no especificado, datos que cambian)?
- [ ] ¿Es tautológica (F idéntica a S, compara algo que no cambia nunca)? Sigue siendo **válida** si se cumple
      (la trivialidad la mide otra métrica), salvo que no se pueda ejecutar.

## Datos de cada API que conviene tener presentes

### PokeAPI (`specs/pokeapi.yaml`)

- Listados (`/api/v2/<recurso>/`): parámetros `limit` y `offset`; respuesta `{count, next, previous, results:
  [{name, url}]}`. El orden es fijo (por id) y los datos **no cambian**: comparar páginas entre peticiones es estable.
- `count` es el total del recurso: no depende de `limit` ni de `offset`.
- Detalle (`/api/v2/<recurso>/{id}/`): el `{id}` acepta el id numérico **o** el nombre (`/pokemon/1/` y
  `/pokemon/bulbasaur/` son el mismo recurso). Si una MR asume que el id N es cierto nombre, compruébalo.
- `pokemon` ≠ `pokemon-species`: una especie agrupa variedades (`varieties[*].pokemon`); el `pokemon` tiene `species`.
  Los ids coinciden para las formas por defecto, no siempre para las demás.

### Crossref (`specs/crossref.json`)

- Respuesta: `{status, message: {total-results, items: [...]}}`. Paginación con `rows` y `offset`.
- **Los datos cambian** (se registran DOIs constantemente). Comparar totales o listas entre peticiones hechas con
  segundos de diferencia suele funcionar, pero una relación que exige igualdad exacta sobre resultados **sin orden
  definido** (sin `sort`) no está garantizada. Con `sort=created&order=asc` el orden es estable.
- **Filtros por endpoint**: cada operación lista en su descripción los filtros que soporta. `/members` solo
  `backfile-doi-count`, `current-doi-count` y `prefix`; `/funders` solo `location`; `/works` tiene muchos más.
  Un filtro de `/works` usado en otro endpoint no es válido.
- `sample=N` devuelve N elementos **aleatorios**: relaciones sobre *qué* elementos salen no pueden garantizarse;
  sobre *cuántos* sí.
- `select` solo reduce los campos de cada elemento; `facet` agrega conteos. Ninguno debería cambiar qué elementos
  ni cuántos.
- Rutas equivalentes que el spec documenta: `/members/{id}/works`, `/prefixes/{prefix}/works`,
  `/funders/{id}/works`, `/types/{id}/works`, `/journals/{issn}/works` listan las obras de esa entidad, como el filtro
  correspondiente en `/works` (`member:`, `prefix:`, `funder:`, `type:`, `issn:`).
- `query` hace búsqueda de texto por relevancia: lo que el spec no dice (mayúsculas, sinónimos) es zona gris; decide
  y deja la razón en `notes`. Lo importante es ser **consistente** entre filas parecidas.

## Después de etiquetar

Desde `experiments/` (dependencias en `AGENTS.md`), por cada API:

```bash
python -m mrexp merge-labels results/pokeapi_labels.csv results/pokeapi_labels_b.csv
python -m mrexp rq1 raw/pokeapi_run1.json --labels results/pokeapi_labels.csv --name pokeapi
```

`merge-labels` copia `label_b` (y las notas) de la copia de B a la hoja de A y lista los desacuerdos. Se resuelven
escribiendo `label_final` en esas filas y luego se corre `rq1`.
