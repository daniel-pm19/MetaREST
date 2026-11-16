// Tipos de autenticación, proyectos, métricas y administración.
// Mantenidos a mano hasta que el backend publique /openapi.json (ver docs/CHECKLIST.md).

export type Role = "admin" | "qa" | "observer";

export const roleLabels: Record<Role, string> = {
  admin: "Administrador",
  qa: "Auditor QA",
  observer: "Observador",
};

export const roleHints: Record<Role, string> = {
  admin: "Control total: usuarios, modelo, umbrales, prompts y revisión.",
  qa: "Revisa MRs: acepta o rechaza, lanza iteraciones y registra proyectos.",
  observer: "Solo lectura: ve el trabajo del auditor sin poder modificarlo.",
};

/** Qué puede hacer cada rol. El backend lo vuelve a comprobar: esto solo decide qué mostrar. */
export interface Permissions {
  decide: boolean; // aceptar / rechazar MRs
  launchRun: boolean; // lanzar una nueva iteración
  manageProjects: boolean; // registrar APIs y subir OpenAPI
  admin: boolean; // usuarios, modelo, umbrales, prompts
}

export const permissionsFor = (role: Role | undefined): Permissions => ({
  decide: role === "admin" || role === "qa",
  launchRun: role === "admin" || role === "qa",
  manageProjects: role === "admin" || role === "qa",
  admin: role === "admin",
});

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  active: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}

export interface NewUser {
  name: string;
  email: string;
  role: Role;
  password: string;
}

export interface Project {
  id: string;
  name: string;
  base_url: string;
  endpoints?: number;
  created_at: string;
}

export interface NewProject {
  name: string;
  base_url: string;
  openapi: string; // texto del OpenAPI (JSON o YAML)
}

export interface RunMetrics {
  run_id: string;
  round: number;
  generated: number;
  discarded: number;
  pending: number;
  accepted: number;
  rejected: number;
  violations: number; // MRs cuya relación se violó
  confirmed_faults: number; // violaciones que el auditor aceptó
  acceptance_rate: number | null; // aceptadas / decididas (0–1)
  tokens: number;
  avg_combined: number; // 0–100
  avg_review_ms: number | null;
}

export interface ThresholdSettings {
  semantic_weight: number;
  fault_weight: number;
  min_semantic: number;
  min_fault_revealing: number;
  similarity_threshold: number;
}

export interface LLMConfig {
  provider: "anthropic" | "gemini";
  generation_model: string;
  verification_model: string;
  max_candidates: number;
  requests_per_minute: number | null;
}

export interface PromptItem {
  id: string;
  kind: "generation" | "semantic" | "fault";
  system: string;
  user: string;
  editable: boolean; // las del repo son de solo lectura
}
