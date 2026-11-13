# Especificaciones de las APIs públicas (SUTs 2 y 3)

Copias **curadas** de los OpenAPI oficiales que se cargan en MetaREST para los experimentos. La curación
solo **quita** cosas (operaciones, parámetros, componentes sin usar); nunca edita lo que declaran las
operaciones que quedan. Se regeneran con [`curate.py`](curate.py) (instrucciones en su docstring).
Por qué se eligieron estas APIs: [`docs/SUTS.md`](../../docs/SUTS.md).

| Archivo | Origen | Versión | sha256 del original (descargado el 13-nov-2026) |
|---|---|---|---|
| `pokeapi.yaml` | <https://raw.githubusercontent.com/PokeAPI/pokeapi/master/openapi.yml> | 2.10.0 (OpenAPI 3.1) | `abda6f26a34c86a4542e9bdaed8a122ef5b9ec5a97695ce84af3605d89e45966` |
| `crossref.json` | <https://api.crossref.org/swagger-docs> | 4.9.1 (Swagger 2.0) | `c13a596239c273cf1f9eeee606c72478bb9ca3f742ce9c061f0fb510baca642b` |

## Cambios respecto al original

### PokeAPI
- **Operaciones: 102 → 15.** Se conservan listado y detalle de `pokemon`, `pokemon-species`, `type`, `ability`,
  `move`, `generation` y `berry`, más `/api/v2/pokemon/{pokemon_id}/encounters`. Con el spec completo el prompt
  de generación ocupa unos 20k tokens y 20 MRs quedan repartidas en 102 operaciones casi idénticas; el
  subconjunto (unos 5k tokens) concentra la generación en los recursos centrales.
- **Se quita el parámetro `q`** (7 operaciones). El propio spec dice que solo existe en instalaciones locales,
  y en `pokeapi.co` responde **403**: una MR que lo usara fallaría siempre por un defecto del spec, no de la API.
- **Para el paper**: la cobertura de operaciones de PokeAPI se mide sobre estas 15.

### Crossref
- **Se quita el parámetro `mailto`** (11 operaciones). Sirve para entrar al *polite pool* con un correo
  personal; el pipeline nunca envía datos personales, así que el LLM no debe proponerlo.
- **Se agregan `host` y `schemes`**, ausentes en el documento original, para que la URL base sea
  `https://api.crossref.org`.
- Se mantiene todo lo demás, incluso `sample` (devuelve elementos aleatorios): sirve para medir si el filtro
  semántico descarta MRs que dependen de él (RQ1).

## Configuración de la SUT al registrar el proyecto

| API | URL base | Concurrencia | Intervalo mínimo | Timeout |
|---|---|---|---|---|
| PokeAPI | `https://pokeapi.co` | 4 | 0 s | 10 s |
| Crossref | `https://api.crossref.org` | 1 | 1 s | 30 s |

Crossref anuncia `x-rate-limit-limit: 1`, `x-rate-limit-interval: 1s` y `x-concurrency-limit: 1` en su pool
público. El ejecutor (`SUTClient`) se identifica con un User-Agent genérico de MetaREST.
