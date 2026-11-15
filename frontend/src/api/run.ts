// Tipos de Run/Decisión. Mientras el backend no publique /openapi.json (npm run gen:types) se mantienen
// a mano, espejando RunReport/StageReport de backend/app/pipeline/orchestrator.py y docs/INTEGRATION.md §1.1.

export type StageName = "extract" | "generate" | "semantic" | "fault_revealing" | "diversity" | "execute";
export type StageStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface StageReport {
  name: StageName;
  status: StageStatus;
  duration_ms?: number | null;
  input_count?: number | null;
  output_count?: number | null;
  usage?: { input_tokens: number; output_tokens: number };
  detail?: string | null;
}

export interface RunReport {
  stages: StageReport[];
  provider?: string | null;
  generation_model?: string | null;
  verification_model?: string | null;
  warnings: string[];
  error?: string | null;
}

export interface Run {
  id: string;
  project_id: string;
  status: "running" | "awaiting_review" | "failed";
  report: RunReport;
  counts: Record<string, number>;
  round: number;
  project_name?: string;
}

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
