import type { LLMConfig, LoginResponse, NewProject, NewUser, Project, PromptItem, Role, RunMetrics, ThresholdSettings, User } from "./admin";
import { initialRun, mockCandidates, nextRoundCandidates } from "./mock";
import { demoAccounts, seedLLM, seedProjects, seedPrompts, seedThresholds, seedUsers, type SeedUser } from "./mockAdmin";
import type { Decision, DecisionInput, Run, StageName } from "./run";
import type { MRCandidate } from "./types";

/**
 * Cliente de la API de MetaREST.
 *
 *  - Con `VITE_API_URL` definido habla con el backend real (endpoints de docs/PLAN.md §1.4).
 *  - Sin él usa datos de demostración persistidos en localStorage, con la misma forma que el backend
 *    y comprobando los permisos por rol igual que lo haría el servidor.
 *
 * Variables: VITE_API_URL, VITE_PROJECT_ID (proyecto que se abre por defecto).
 */
const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "");
export const DEFAULT_PROJECT_ID = (import.meta.env.VITE_PROJECT_ID as string | undefined) ?? "proj_demo";
export const isMock = !API_URL;
export { demoAccounts };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

// ───────────────────────────────── Sesión ─────────────────────────────────

const TOKEN_KEY = "metarest-token";
let token: string | null = sessionStorage.getItem(TOKEN_KEY);
let onUnauthorized: (() => void) | null = null;

export const session = {
  get token() {
    return token;
  },
  set(t: string | null) {
    token = t;
    if (t) sessionStorage.setItem(TOKEN_KEY, t);
    else sessionStorage.removeItem(TOKEN_KEY);
  },
  onUnauthorized(fn: () => void) {
    onUnauthorized = fn;
  },
};

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError("No se pudo conectar con el servidor. Revisa que el backend esté en marcha.");
  }
  if (res.status === 401 && path !== "/auth/login") onUnauthorized?.();
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* sin cuerpo JSON */
    }
    const fallback = res.status === 403 ? "Tu rol no tiene permiso para hacer esto." : `Error ${res.status} del servidor`;
    throw new ApiError(detail || fallback, res.status);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

// ───────────────────────────── Modo demostración ─────────────────────────────

const KEY = "metarest-mock-v3";
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const STAGES: StageName[] = ["extract", "generate", "semantic", "fault_revealing", "diversity", "execute"];
const STAGE_MS = 1100;

interface MockDb {
  runs: Run[];
  candidates: MRCandidate[];
  decisions: Decision[];
  projects: Project[];
  users: SeedUser[];
  thresholds: ThresholdSettings;
  llm: LLMConfig;
  prompts: PromptItem[];
  startedAt?: number;
}

function loadDb(): MockDb {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as MockDb;
  } catch {
    /* corrupto: se reinicia */
  }
  return {
    runs: [initialRun()],
    candidates: mockCandidates,
    decisions: [],
    projects: seedProjects,
    users: seedUsers,
    thresholds: seedThresholds,
    llm: seedLLM,
    prompts: seedPrompts,
  };
}
const saveDb = (db: MockDb) => localStorage.setItem(KEY, JSON.stringify(db));

/** Avanza el run simulado según el tiempo transcurrido. */
function tick(db: MockDb): MockDb {
  const last = db.runs[db.runs.length - 1];
  if (!last || last.status !== "running" || !db.startedAt) return db;
  const done = Math.floor((Date.now() - db.startedAt) / STAGE_MS);
  if (done >= STAGES.length) {
    db.runs[db.runs.length - 1] = { ...initialRun(), id: last.id, round: last.round };
    db.candidates = [...db.candidates, ...nextRoundCandidates];
    db.startedAt = undefined;
  } else {
    last.report.stages = last.report.stages.map((s, i) => ({ ...s, status: i < done ? "done" : i === done ? "running" : "pending" }));
  }
  saveDb(db);
  return db;
}

/** Usuario de la sesión demo; lanza 401/403 como lo haría el backend. */
function mockUser(db: MockDb, ...roles: Role[]): User {
  const id = token?.startsWith("mock-") ? token.slice(5) : null;
  const u = db.users.find((x) => x.id === id && x.active);
  if (!u) {
    onUnauthorized?.();
    throw new ApiError("Tu sesión expiró. Inicia sesión de nuevo.", 401);
  }
  if (roles.length && !roles.includes(u.role)) throw new ApiError("Tu rol no tiene permiso para hacer esto.", 403);
  return u;
}
const strip = ({ password: _p, ...u }: SeedUser): User => u;

function countEndpoints(text: string): number {
  try {
    const spec = JSON.parse(text);
    return Object.values(spec.paths ?? {}).filter((p) => p && typeof p === "object" && "get" in (p as object)).length;
  } catch {
    return (text.match(/^\s+get:/gm) ?? []).length;
  }
}

// ──────────────────────────────── API pública ────────────────────────────────

export const api = {
  // — Autenticación —
  async login(email: string, password: string): Promise<LoginResponse> {
    if (API_URL) return http<LoginResponse>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    await wait(400);
    const u = loadDb().users.find((x) => x.email.toLowerCase() === email.trim().toLowerCase());
    if (!u || u.password !== password) throw new ApiError("Correo o contraseña incorrectos.", 401);
    if (!u.active) throw new ApiError("Esta cuenta está desactivada. Contacta a un administrador.", 403);
    return { access_token: `mock-${u.id}`, token_type: "bearer", user: strip(u) };
  },

  async me(): Promise<User> {
    if (API_URL) return http<User>("/auth/me");
    return strip(mockUser(loadDb()) as SeedUser);
  },

  // — Proyectos —
  async listProjects(): Promise<Project[]> {
    if (API_URL) return http<Project[]>("/projects");
    await wait(200);
    const db = loadDb();
    mockUser(db);
    return db.projects;
  },

  async createProject(p: NewProject): Promise<Project> {
    if (API_URL) return http<Project>("/projects", { method: "POST", body: JSON.stringify(p) });
    await wait(500);
    const db = loadDb();
    mockUser(db, "admin", "qa");
    if (!/openapi|swagger/i.test(p.openapi)) throw new ApiError("El archivo no parece una especificación OpenAPI (falta «openapi» o «swagger»).", 422);
    const created: Project = {
      id: `proj_${Date.now().toString(36)}`,
      name: p.name,
      base_url: p.base_url,
      endpoints: countEndpoints(p.openapi),
      created_at: new Date().toISOString(),
    };
    db.projects.push(created);
    saveDb(db);
    return created;
  },

  // — Runs, candidatas y decisiones —
  async listRuns(projectId: string): Promise<Run[]> {
    if (API_URL) return http<Run[]>(`/projects/${projectId}/runs`);
    await wait(250);
    const db = tick(loadDb());
    mockUser(db);
    const project = db.projects.find((p) => p.id === projectId);
    return projectId === "proj_demo" ? db.runs.map((r) => ({ ...r, project_id: projectId, project_name: project?.name })) : [];
  },

  async getRun(runId: string): Promise<Run> {
    if (API_URL) return http<Run>(`/runs/${runId}`);
    const db = tick(loadDb());
    const r = db.runs.find((x) => x.id === runId);
    if (!r) throw new ApiError("Iteración no encontrada.", 404);
    return r;
  },

  async listCandidates(runId: string): Promise<MRCandidate[]> {
    if (API_URL) return http<MRCandidate[]>(`/runs/${runId}/candidates`);
    await wait(200);
    return tick(loadDb()).candidates.filter((c) => c.run_id === runId);
  },

  /** Lanza una nueva iteración del pipeline. Devuelve el run en curso (202). */
  async startRun(projectId: string): Promise<Run> {
    if (API_URL) return http<Run>(`/projects/${projectId}/runs`, { method: "POST" });
    await wait(300);
    const db = loadDb();
    mockUser(db, "admin", "qa");
    if (projectId !== "proj_demo") throw new ApiError("En modo demostración solo el proyecto de ejemplo puede ejecutar iteraciones.", 400);
    if (db.runs.some((r) => r.status === "running")) throw new ApiError("Ya hay una iteración en curso.", 409);
    const run: Run = {
      ...initialRun(),
      id: `run_00${db.runs.length + 1}`,
      status: "running",
      round: db.runs.length + 1,
      report: { ...initialRun().report, stages: STAGES.map((name) => ({ name, status: "pending" as const })) },
    };
    db.runs.push(run);
    db.startedAt = Date.now();
    saveDb(db);
    return run;
  },

  /** Registra la decisión (append-only en el backend). Rechazar exige justificación. */
  async decide(candidateId: string, input: DecisionInput): Promise<void> {
    if (API_URL) {
      await http(`/candidates/${candidateId}/decision`, { method: "POST", body: JSON.stringify(input) });
      return;
    }
    await wait(250);
    const db = loadDb();
    const user = mockUser(db, "admin", "qa");
    const c = db.candidates.find((x) => x.id === candidateId);
    if (!c || c.status !== "pending_review") throw new ApiError("Solo se pueden decidir candidatas pendientes de revisión.", 409);
    if (input.decision === "rejected" && !input.justification?.trim()) throw new ApiError("Rechazar exige una justificación.", 422);
    c.status = input.decision;
    db.decisions.unshift({
      id: `dec_${Date.now()}`,
      candidate_id: candidateId,
      title: c.spec?.title ?? candidateId,
      decision: input.decision,
      justification: input.justification,
      review_time_ms: input.review_time_ms,
      user: user.name,
      at: new Date().toISOString(),
    });
    saveDb(db);
  },

  async listDecisions(runId: string): Promise<Decision[]> {
    if (API_URL) return http<Decision[]>(`/audit?run_id=${encodeURIComponent(runId)}`);
    await wait(150);
    const db = loadDb();
    const ids = new Set(db.candidates.filter((c) => c.run_id === runId).map((c) => c.id));
    return db.decisions.filter((d) => ids.has(d.candidate_id));
  },

  // — Métricas —
  async compareRuns(runIds: string[]): Promise<RunMetrics[]> {
    if (API_URL) return http<RunMetrics[]>(`/metrics/compare?runs=${runIds.join(",")}`);
    await wait(250);
    const db = loadDb();
    return runIds.flatMap((id) => {
      const run = db.runs.find((r) => r.id === id);
      if (!run) return [];
      const cs = db.candidates.filter((c) => c.run_id === id);
      const kept = cs.filter((c) => c.status !== "discarded");
      const n = (s: string) => cs.filter((c) => c.status === s).length;
      const decs = db.decisions.filter((d) => cs.some((c) => c.id === d.candidate_id));
      const times = decs.map((d) => d.review_time_ms).filter((t): t is number => typeof t === "number");
      const accepted = n("accepted");
      const rejected = n("rejected");
      return [
        {
          run_id: id,
          round: run.round,
          generated: cs.length,
          discarded: n("discarded"),
          pending: n("pending_review"),
          accepted,
          rejected,
          violations: kept.filter((c) => c.execution?.verdict === "violation").length,
          confirmed_faults: kept.filter((c) => c.status === "accepted" && c.execution?.verdict === "violation").length,
          acceptance_rate: accepted + rejected ? accepted / (accepted + rejected) : null,
          tokens: run.report.stages.reduce((a, s) => a + (s.usage?.input_tokens ?? 0) + (s.usage?.output_tokens ?? 0), 0),
          avg_combined: kept.length ? Math.round((kept.reduce((a, c) => a + (c.scores?.combined ?? 0), 0) / kept.length) * 100) : 0,
          avg_review_ms: times.length ? Math.round(times.reduce((a, b) => a + b, 0) / times.length) : null,
        },
      ];
    });
  },

  // — Administración (solo Admin) —
  async listUsers(): Promise<User[]> {
    if (API_URL) return http<User[]>("/users");
    await wait(200);
    const db = loadDb();
    mockUser(db, "admin");
    return db.users.map(strip);
  },

  async createUser(u: NewUser): Promise<User> {
    if (API_URL) return http<User>("/users", { method: "POST", body: JSON.stringify(u) });
    await wait(400);
    const db = loadDb();
    mockUser(db, "admin");
    if (db.users.some((x) => x.email.toLowerCase() === u.email.toLowerCase())) throw new ApiError("Ya existe un usuario con ese correo.", 409);
    const created: SeedUser = { id: `u_${Date.now().toString(36)}`, name: u.name, email: u.email, role: u.role, active: true, password: u.password };
    db.users.push(created);
    saveDb(db);
    return strip(created);
  },

  async updateUser(id: string, patch: Partial<Pick<User, "role" | "active">>): Promise<User> {
    if (API_URL) return http<User>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
    await wait(250);
    const db = loadDb();
    const me = mockUser(db, "admin");
    const u = db.users.find((x) => x.id === id);
    if (!u) throw new ApiError("Usuario no encontrado.", 404);
    if (u.id === me.id) throw new ApiError("No puedes cambiar tu propio rol ni desactivarte.", 400);
    Object.assign(u, patch);
    saveDb(db);
    return strip(u);
  },

  async getThresholds(): Promise<ThresholdSettings> {
    if (API_URL) return http<ThresholdSettings>("/settings/thresholds");
    await wait(150);
    const db = loadDb();
    mockUser(db, "admin");
    return db.thresholds;
  },
  async saveThresholds(s: ThresholdSettings): Promise<ThresholdSettings> {
    if (API_URL) return http<ThresholdSettings>("/settings/thresholds", { method: "PUT", body: JSON.stringify(s) });
    await wait(300);
    const db = loadDb();
    mockUser(db, "admin");
    db.thresholds = s;
    saveDb(db);
    return s;
  },

  async getLLM(): Promise<LLMConfig> {
    if (API_URL) return http<LLMConfig>("/settings/llm");
    await wait(150);
    const db = loadDb();
    mockUser(db, "admin");
    return db.llm;
  },
  async saveLLM(s: LLMConfig): Promise<LLMConfig> {
    if (API_URL) return http<LLMConfig>("/settings/llm", { method: "PUT", body: JSON.stringify(s) });
    await wait(300);
    const db = loadDb();
    mockUser(db, "admin");
    db.llm = s;
    saveDb(db);
    return s;
  },

  async listPrompts(): Promise<PromptItem[]> {
    if (API_URL) return http<PromptItem[]>("/prompts");
    await wait(150);
    const db = loadDb();
    mockUser(db, "admin");
    return db.prompts;
  },
  async createPrompt(p: Omit<PromptItem, "editable">): Promise<PromptItem> {
    if (API_URL) return http<PromptItem>("/prompts", { method: "POST", body: JSON.stringify(p) });
    await wait(300);
    const db = loadDb();
    mockUser(db, "admin");
    if (db.prompts.some((x) => x.id === p.id)) throw new ApiError("Ya existe un prompt con ese id.", 409);
    const created = { ...p, editable: true };
    db.prompts.push(created);
    saveDb(db);
    return created;
  },

  resetDemo() {
    localStorage.removeItem(KEY);
  },
};
