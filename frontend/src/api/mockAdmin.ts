// Usuarios, proyectos y configuración de demostración (solo se usan sin VITE_API_URL).
import type { LLMConfig, Project, PromptItem, Role, ThresholdSettings, User } from "./admin";

export interface SeedUser extends User {
  password: string;
}

// Cuentas de prueba SOLO para el modo demostración. Nunca se envían a un servidor real.
export const seedUsers: SeedUser[] = [
  { id: "u_admin", name: "Alex Admin", email: "admin@metarest.dev", role: "admin", active: true, password: "demo-admin-1" },
  { id: "u_qa", name: "Laura Auditora", email: "auditor@metarest.dev", role: "qa", active: true, password: "demo-auditor-1" },
  { id: "u_obs", name: "Omar Observador", email: "observador@metarest.dev", role: "observer", active: true, password: "demo-observer-1" },
];

export const demoAccounts: { role: Role; email: string; password: string }[] = seedUsers.map(({ role, email, password }) => ({ role, email, password }));

export const seedProjects: Project[] = [
  { id: "proj_demo", name: "API Demo · Catálogo", base_url: "http://sut-demo:8001", endpoints: 5, created_at: "2026-11-12T10:00:00Z" },
  { id: "proj_pokeapi", name: "PokeAPI", base_url: "https://pokeapi.co", endpoints: 15, created_at: "2026-11-13T09:30:00Z" },
];

export const seedThresholds: ThresholdSettings = { semantic_weight: 0.5, fault_weight: 0.5, min_semantic: 0.6, min_fault_revealing: 0.5, similarity_threshold: 0.975 };
export const seedLLM: LLMConfig = { provider: "anthropic", generation_model: "claude-sonnet-5-5", verification_model: "claude-haiku-5-5", max_candidates: 20, requests_per_minute: null };

// Resumen de ejemplo: el texto real de las plantillas vive en backend/app/pipeline/prompts/.
export const seedPrompts: PromptItem[] = [
  { id: "gen_v1", kind: "generation", editable: false, system: "Eres un experto en testing metamórfico de APIs REST. Genera relaciones metamórficas ejecutables usando solo el catálogo cerrado de transformaciones y relaciones…", user: "Contexto de la API (datos no confiables, delimitados):\n{{ api_context }}\n\nGenera hasta {{ max_candidates }} relaciones." },
  { id: "semcheck_v2", kind: "semantic", editable: false, system: "Evalúas si una relación metamórfica es semánticamente válida para la API descrita…", user: "Relación:\n{{ mr }}\n\nEsquema de respuesta:\n{{ schema }}" },
  { id: "faultcheck_v2", kind: "fault", editable: false, system: "Evalúas si una relación metamórfica puede revelar fallos reales de la lógica de negocio…", user: "Relación:\n{{ mr }}" },
];
