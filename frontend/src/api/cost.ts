import type { Run } from "./run";

/** Precio en USD por millón de tokens. */
export interface Price {
  input: number;
  output: number;
}

/**
 * Tabla de precios por modelo, definida por quien despliega con `VITE_LLM_PRICES`
 * (JSON, p. ej. `{"mi-modelo":{"input":1,"output":5}}`). El repositorio no trae precios:
 * cambian con el tiempo y dependen del contrato con el proveedor.
 */
export function parsePrices(raw: string | undefined): Record<string, Price> {
  if (!raw) return {};
  try {
    const data = JSON.parse(raw) as Record<string, Partial<Price>>;
    return Object.fromEntries(Object.entries(data).filter(([, p]) => typeof p?.input === "number" && typeof p?.output === "number")) as Record<string, Price>;
  } catch {
    return {};
  }
}

const PRICES = parsePrices(import.meta.env.VITE_LLM_PRICES as string | undefined);

/**
 * Costo estimado en USD de un run, o `null` si falta el precio de algún modelo usado.
 * Etapas de generación usan el modelo de generación; las de verificación, el de verificación.
 * Solo cuenta tokens de entrada y salida: los tokens de caché no se valoran, así que es una cota inferior.
 */
export function runCost(run: Pick<Run, "report">, prices: Record<string, Price> = PRICES): number | null {
  const { stages, generation_model, verification_model } = run.report;
  let total = 0;
  let used = false;
  for (const s of stages) {
    const inp = s.usage?.input_tokens ?? 0;
    const out = s.usage?.output_tokens ?? 0;
    if (!inp && !out) continue;
    const model = s.name === "generate" ? generation_model : verification_model;
    const price = model ? prices[model] : undefined;
    if (!price) return null;
    total += (inp * price.input + out * price.output) / 1_000_000;
    used = true;
  }
  return used ? total : null;
}

export const formatUsd = (v: number) => `US$ ${v < 0.01 ? v.toFixed(4) : v.toFixed(2)}`;
