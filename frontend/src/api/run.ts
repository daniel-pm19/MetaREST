// Tipos de Run derivados del esquema OpenAPI del backend (npm run gen:types). Decision no tiene
// response_model en /audit, por lo que se mantiene a mano según docs/API.md.
import type { components } from "./schema";

type Schemas = components["schemas"];
export type StageName = Schemas["StageName"];
export type StageStatus = Schemas["StageStatus"];
// El servidor siempre envía stages/warnings; el esquema los marca opcionales por tener valor por defecto.
export type StageReport = Omit<Schemas["StageReport"], "usage"> & { usage?: Partial<Schemas["TokenUsage"]> & { input_tokens: number; output_tokens: number } };
export type RunReport = Omit<Schemas["RunReport"], "stages" | "warnings" | "fallback_used"> & {
  stages: StageReport[];
  warnings: string[];
  fallback_used?: boolean;
};
export type Run = Omit<Schemas["RunOutput"], "report" | "project_name"> & { report: RunReport; project_name?: string };

export interface Decision {
  id: string;
  candidate_id: string;
  title: string;
  decision: "accepted" | "rejected";
  justification?: string | null;
  review_time_ms?: number | null;
  user?: string | null; // nombre de quien decidió
  at: string;
}

export interface DecisionInput {
  decision: "accepted" | "rejected";
  justification?: string;
  review_time_ms?: number;
}
