// Datos de demostración con la forma exacta de MRCandidate (docs/mr_examples/). Solo se usan sin VITE_API_URL.
import type { MRCandidate } from "./types";
import type { Run } from "./run";

type Q = Record<string, string | number>;
interface Seed {
  id: string;
  title: string;
  description: string;
  q: Q;
  follow: unknown[];
  rel: Record<string, unknown>;
  logic: string;
  expected: string;
  rationale: string;
  sem: number;
  fault: number;
  sim?: number;
  verdict?: "pass" | "violation" | "error";
  msg?: string;
  round?: number;
}

const base = { project_id: "proj_demo", run_id: "run_001", schema_version: "1.0" };
const prov = { provider: "anthropic", model: "claude-sonnet-5-5", prompt_version: "gen_v1", generated_at: "2026-11-14T15:02:11Z" };
const url = (p: string, q: Q) =>
  `http://sut-demo:8001${p}?${Object.entries(q)
    .map(([k, v]) => `${k}=${v}`)
    .join("&")}`;
const ex = (q: Q, ms: number, sel: string) => ({
  method: "GET",
  url: url("/search", q),
  status_code: 200,
  elapsed_ms: ms,
  response_excerpt: '{"total": 57, "results": [{"id": 3, ...}, ...]}',
  selected_excerpt: sel,
});

function pending(s: Seed): MRCandidate {
  const verdict = s.verdict ?? "pass";
  return {
    ...base,
    run_id: s.round === 2 ? "run_002" : "run_001",
    id: s.id,
    status: "pending_review",
    spec: {
      title: s.title,
      description: s.description,
      source: { method: "GET", path: "/search", query_params: s.q },
      followups: s.follow,
      relation: s.rel,
      transformation_logic: s.logic,
      expected_relation: s.expected,
      rationale: s.rationale,
    },
    provenance: prov,
    scores: {
      semantic_validity: { rules_passed: true, llm_score: s.sem, llm_reason: "Los parámetros y el selector existen en el OpenAPI.", score: s.sem },
      fault_revealing: { rules_passed: true, llm_score: s.fault, llm_reason: "Es una zona de la API propensa a defectos de lógica.", score: s.fault },
      max_similarity: s.sim ?? 0.5,
      combined: +((s.sem + s.fault) / 2).toFixed(2),
    },
    filter_result: { passed: true },
    execution: {
      verdict,
      executed_at: "2026-11-14T15:03:40Z",
      instances: [
        {
          index: 0,
          verdict,
          message: s.msg ?? (verdict === "pass" ? "La relación se cumple." : undefined),
          source: ex(s.q, 34.2, "[3, 5, 8, 12, 14, 19]"),
          followups: [ex({ ...s.q, variante: "follow-up" }, 29.8, verdict === "violation" ? "[3, 5, 87, 91]" : "[3, 5, 8]")],
        },
      ],
    },
  } as unknown as MRCandidate;
}

function discarded(id: string, title: string, reason: string, stage: string, detail: string, dup?: string): MRCandidate {
  return {
    ...base,
    id,
    status: "discarded",
    provenance: prov,
    scores: { max_similarity: dup ? 0.98 : null },
    filter_result: { passed: false, stage, reason, detail, duplicate_of: dup ?? null },
    spec: {
      title,
      description: "Candidata descartada por el filtro automático.",
      source: { method: "GET", path: "/search", query_params: { q: "jazz", limit: 10 } },
      followups: [{ transformations: [{ op: "set_param", param: "limit", value: 5 }] }],
      relation: { type: "subset", source_selector: "$.results[*].id", direction: "followup_in_source" },
      transformation_logic: "Se cambia limit.",
      expected_relation: "results(limit=5) ⊆ results(limit=10)",
      rationale: "Verifica que limit se respete.",
    },
  } as unknown as MRCandidate;
}

const sub = { type: "subset", source_selector: "$.results[*].id", direction: "followup_in_source" };
const eq = { type: "equivalence", source_selector: "$.results[*].id" };

export const mockCandidates: MRCandidate[] = [
  pending({
    id: "cand_01",
    title: "Reducir limit devuelve un subconjunto",
    description: "Al bajar el limit de una búsqueda, los resultados deben estar contenidos en los de la búsqueda original.",
    q: { q: "jazz", limit: 20 },
    follow: [{ transformations: [{ op: "scale_param", param: "limit", factor: 0.5 }] }],
    rel: sub,
    logic: "Se divide limit entre 2 (20 → 10).",
    expected: "results(limit=10) ⊆ results(limit=20)",
    rationale: "Detecta APIs cuyo orden o filtrado cambia según el tamaño de página.",
    sem: 0.92,
    fault: 0.8,
    sim: 0.41,
    verdict: "violation",
    msg: "2 ids del follow-up no están en la respuesta fuente: [87, 91]",
  }),
  pending({
    id: "cand_02",
    title: "El orden de los parámetros no altera el resultado",
    description: "Aplicar q y category en distinto orden debe devolver el mismo conjunto.",
    q: { q: "jazz", category: "music" },
    follow: [
      {
        transformations: [
          { op: "remove_param", param: "category" },
          { op: "add_param", param: "category", value: "music" },
        ],
      },
    ],
    rel: eq,
    logic: "Se reordenan los parámetros de consulta.",
    expected: "set(res₂) == set(res₁)",
    rationale: "Un parser sensible al orden de parámetros sería un bug.",
    sem: 0.9,
    fault: 0.68,
    sim: 0.6,
  }),
  pending({
    id: "cand_03",
    title: "Páginas 1 y 2 completan una petición de limit doble",
    description: "La unión de dos páginas consecutivas debe coincidir con una única petición de tamaño doble.",
    q: { q: "jazz", limit: 10, page: 1 },
    follow: [{ transformations: [{ op: "set_param", param: "page", value: 2 }] }, { transformations: [{ op: "set_param", param: "limit", value: 20 }] }],
    rel: { type: "complete", source_selector: "$.results[*].id" },
    logic: "Se pide la página 2 y una petición de limit 20.",
    expected: "p1 ∪ p2 == res(limit=20)",
    rationale: "Errores off-by-one aparecen con frecuencia en paginación.",
    sem: 0.86,
    fault: 0.9,
    sim: 0.55,
    verdict: "violation",
    msg: "Falta el id 41 al unir páginas: posible desfase off-by-one.",
  }),
  pending({
    id: "cand_04",
    title: "Más filtros nunca aumentan el total",
    description: "Añadir un filtro por categoría no puede aumentar el número de resultados.",
    q: { q: "jazz" },
    follow: [{ transformations: [{ op: "add_param", param: "category", value: "music" }] }],
    rel: { type: "count_leq", source_selector: "$.total", direction: "followup_in_source", measure: "value" },
    logic: "Se añade category=music.",
    expected: "total(con filtro) ≤ total(sin filtro)",
    rationale: "Un filtro restrictivo solo puede quitar elementos.",
    sem: 0.95,
    fault: 0.74,
    sim: 0.38,
  }),
  pending({
    id: "cand_05",
    title: "Invertir el orden mantiene el orden relativo común",
    description: "Los elementos comunes entre ambos órdenes deben conservar su posición relativa.",
    q: { q: "guitar", sort: "price_asc" },
    follow: [{ transformations: [{ op: "set_param", param: "sort", value: "price_desc" }] }],
    rel: { type: "same_order", source_selector: "$.results[*].id" },
    logic: "Se cambia sort a price_desc.",
    expected: "orden común conservado",
    rationale: "Ordenamientos inestables suelen romper esta propiedad.",
    sem: 0.72,
    fault: 0.7,
    sim: 0.7,
    verdict: "error",
    msg: "El follow-up devolvió 422: sort=price_desc no es un valor válido.",
  }),
  pending({
    id: "cand_06",
    title: "Buscar en mayúsculas o minúsculas da lo mismo",
    description: "La búsqueda de texto no debería depender de la capitalización.",
    q: { q: "laptop" },
    follow: [{ transformations: [{ op: "set_param", param: "q", value: "LAPTOP" }] }],
    rel: eq,
    logic: "q pasa a mayúsculas.",
    expected: "res₂ == res₁",
    rationale: "Un usuario espera resultados idénticos.",
    sem: 0.82,
    fault: 0.61,
    sim: 0.66,
  }),
  pending({
    id: "cand_08",
    title: "Ampliar limit solo añade resultados",
    description: "Con limit=10 los resultados deben estar contenidos en los de limit=50.",
    q: { q: "drums", limit: 10 },
    follow: [{ transformations: [{ op: "set_param", param: "limit", value: 50 }] }],
    rel: { ...sub, direction: "source_in_followup" },
    logic: "limit pasa de 10 a 50.",
    expected: "res(10) ⊆ res(50)",
    rationale: "Detecta cortes incorrectos al ampliar la página.",
    sem: 0.88,
    fault: 0.77,
    sim: 0.72,
  }),
  discarded("cand_07", "Limit menor devuelve elementos contenidos", "redundant", "diversity", "Similitud 0.98 con cand_01 (umbral 0.975).", "cand_01"),
  discarded(
    "cand_09",
    "El total es igual a la suma de resultados",
    "invalid_semantics",
    "semantic",
    "El campo $.sum no existe en el esquema de respuesta de GET /search.",
  ),
  discarded(
    "cand_10",
    "Repetir la misma búsqueda da lo mismo",
    "low_fault_revealing",
    "fault_revealing",
    "Relación tautológica: la petición origen y la derivada son idénticas.",
  ),
  {
    ...base,
    id: "cand_11",
    status: "discarded",
    provenance: prov,
    spec: null,
    scores: {},
    raw_output: { title: "Crear un producto y buscarlo", source: { method: "POST", path: "/products" } },
    filter_result: { passed: false, stage: "schema", reason: "not_executable", detail: "source.method: Input should be 'GET' or 'HEAD'" },
  } as unknown as MRCandidate,
];

export const nextRoundCandidates: MRCandidate[] = [
  pending({
    id: "cand_12",
    round: 2,
    title: "Una página inexistente no repite elementos",
    description: "Pedir una página muy alta no debe devolver elementos ya vistos.",
    q: { q: "jazz", limit: 10, page: 1 },
    follow: [{ transformations: [{ op: "set_param", param: "page", value: 999 }] }],
    rel: { type: "disjoint", source_selector: "$.results[*].id" },
    logic: "page pasa a 999.",
    expected: "res(p999) ∩ res(p1) = ∅",
    rationale: "Prioriza casos límite de paginación a partir de tu feedback.",
    sem: 0.9,
    fault: 0.86,
    sim: 0.35,
  }),
  pending({
    id: "cand_13",
    round: 2,
    title: "Duplicar limit no reduce la cantidad",
    description: "Doblar limit no puede devolver menos elementos.",
    q: { q: "drums", limit: 5 },
    follow: [{ transformations: [{ op: "scale_param", param: "limit", factor: 2 }] }],
    rel: { type: "count_leq", source_selector: "$.results", direction: "source_in_followup" },
    logic: "limit × 2.",
    expected: "count(limit=5) ≤ count(limit=10)",
    rationale: "Aporta diversidad frente a las MRs de subconjunto.",
    sem: 0.93,
    fault: 0.79,
    sim: 0.4,
  }),
];

export const initialRun = (): Run => ({
  id: "run_001",
  project_id: "proj_demo",
  project_name: "API Demo · Catálogo",
  status: "awaiting_review",
  round: 1,
  counts: {},
  report: {
    provider: "anthropic",
    generation_model: "claude-sonnet-5-5",
    verification_model: "claude-haiku-5-5",
    warnings: [],
    stages: [
      { name: "extract", status: "done", duration_ms: 420, input_count: 1, output_count: 5 },
      { name: "generate", status: "done", duration_ms: 41200, input_count: 5, output_count: 20, usage: { input_tokens: 6120, output_tokens: 7340 } },
      { name: "semantic", status: "done", duration_ms: 18300, input_count: 20, output_count: 17, usage: { input_tokens: 9800, output_tokens: 1900 } },
      { name: "fault_revealing", status: "done", duration_ms: 17100, input_count: 17, output_count: 16, usage: { input_tokens: 9200, output_tokens: 1700 } },
      { name: "diversity", status: "done", duration_ms: 890, input_count: 16, output_count: 15 },
      { name: "execute", status: "done", duration_ms: 5200, input_count: 15, output_count: 15 },
    ],
  },
});
