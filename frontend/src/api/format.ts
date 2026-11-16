import type { MRCandidate, MRSpec, RequestSpec } from "./types";

type Transformation = NonNullable<NonNullable<MRSpec["followups"][number]["transformations"]>[number]>;

export const pct = (v?: number | null) => (v == null ? 0 : Math.round(v * 100));

/** /search?q=jazz&limit=20 */
export function requestLine(r: RequestSpec): string {
  let path = r.path;
  for (const [k, v] of Object.entries(r.path_params ?? {})) path = path.replace(`{${k}}`, String(v));
  const qs = Object.entries(r.query_params ?? {})
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(",") : v}`)
    .join("&");
  return qs ? `${path}?${qs}` : path;
}

export function transformationLabel(t: Transformation): string {
  switch (t.op) {
    case "set_param":
      return `Fijar ${t.param} = ${JSON.stringify(t.value)}`;
    case "remove_param":
      return `Quitar ${t.param}`;
    case "add_param":
      return `Añadir ${t.param} = ${JSON.stringify(t.value)}`;
    case "scale_param":
      return `Multiplicar ${t.param} por ${t.factor}`;
    case "append_to_param":
      return `Añadir «${t.value}» a ${t.param}`;
    case "move_param":
      return `Mover ${t.param} de ${t.from_location} a ${t.to_location}${t.to_param ? ` (${t.to_param})` : ""}`;
  }
}

export const relationLabels: Record<string, string> = {
  equality: "Igualdad",
  equivalence: "Equivalencia",
  subset: "Subconjunto",
  disjoint: "Disjuntos",
  complete: "Completitud",
  difference: "Diferencia",
  count_leq: "Cantidad ≤",
  same_order: "Mismo orden",
};

export const reasonLabels: Record<string, string> = {
  not_executable: "No ejecutable",
  invalid_semantics: "Semántica inválida",
  low_fault_revealing: "Poco reveladora",
  redundant: "Redundante",
};

export const stageLabels: Record<string, string> = {
  extract: "Extracción de contexto",
  generate: "Generación con LLM",
  semantic: "Validez semántica",
  fault_revealing: "Potencial de fallos",
  diversity: "Diversidad funcional",
  execute: "Ejecución contra la API",
};

export const titleOf = (c: MRCandidate) => c.spec?.title ?? "Salida del LLM no ejecutable";
export const combined = (c: MRCandidate) => pct(c.scores?.combined);
