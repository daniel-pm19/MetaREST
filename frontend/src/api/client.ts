import { initialRun, mockCandidates, nextRoundCandidates } from "./mock";
import type { Decision, DecisionInput, Run, StageName } from "./run";
import type { MRCandidate } from "./types";

/**
 * Cliente de la API de MetaREST.
 *
 *  - Con `VITE_API_URL` definido habla con el backend real (endpoints de docs/PLAN.md §1.4).
 *  - Sin él usa datos de demostración persistidos en localStorage, con la misma forma que el backend.
 *
 * Variables: VITE_API_URL, VITE_PROJECT_ID (proyecto a analizar), VITE_RUN_ID (run a revisar al abrir).
 */
const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "");
export const PROJECT_ID = (import.meta.env.VITE_PROJECT_ID as string | undefined) ?? "proj_demo";
export const RUN_ID = (import.meta.env.VITE_RUN_ID as string | undefined) ?? "run_001";
export const isMock = !API_URL;

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("No se pudo conectar con el servidor. Revisa que el backend esté en marcha.");
  }
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* sin cuerpo JSON */
    }
    throw new ApiError(detail || `Error ${res.status} del servidor`, res.status);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

// ───────────────────────────── Modo demostración ─────────────────────────────

const KEY = "metarest-mock-v2";
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const STAGES: StageName[] = ["extract", "generate", "semantic", "fault_revealing", "diversity", "execute"];
const STAGE_MS = 1100;

interface MockDb {
  run: Run;
  candidates: MRCandidate[];
  decisions: Decision[];
  startedAt?: number;
}

function loadDb(): MockDb {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as MockDb;
  } catch {
    /* corrupto: se reinicia */
  }
  return { run: initialRun(), candidates: mockCandidates, decisions: [] };
}
const saveDb = (db: MockDb) => localStorage.setItem(KEY, JSON.stringify(db));

/** Avanza el run simulado según el tiempo transcurrido. */
function tick(db: MockDb): MockDb {
  if (db.run.status !== "running" || !db.startedAt) return db;
  const done = Math.floor((Date.now() - db.startedAt) / STAGE_MS);
  if (done >= STAGES.length) {
    db.run = { ...initialRun(), id: "run_002", round: 2 };
    db.candidates = [...db.candidates, ...nextRoundCandidates];
    db.startedAt = undefined;
  } else {
    db.run = {
      ...db.run,
      report: {
        ...db.run.report,
        stages: db.run.report.stages.map((s, i) => ({ ...s, status: i < done ? "done" : i === done ? "running" : "pending" })),
      },
    };
  }
  saveDb(db);
  return db;
}

// ──────────────────────────────── API pública ────────────────────────────────

export const api = {
  async getRun(runId: string): Promise<Run> {
    if (API_URL) return http<Run>(`/runs/${runId}`);
    await wait(350);
    return tick(loadDb()).run;
  },

  async listCandidates(runId: string): Promise<MRCandidate[]> {
    if (API_URL) return http<MRCandidate[]>(`/runs/${runId}/candidates`);
    await wait(250);
    const db = tick(loadDb());
    return db.candidates.filter((c) => db.run.round === 2 || c.run_id === "run_001");
  },

  /** Lanza una nueva iteración del pipeline. Devuelve el run en curso (202). */
  async startRun(projectId: string): Promise<Run> {
    if (API_URL) return http<Run>(`/projects/${projectId}/runs`, { method: "POST" });
    await wait(300);
    const db = loadDb();
    db.run = {
      ...db.run,
      id: "run_002",
      status: "running",
      round: 2,
      report: { ...db.run.report, stages: STAGES.map((name) => ({ name, status: "pending" as const })) },
    };
    db.startedAt = Date.now();
    saveDb(db);
    return db.run;
  },

  /** Registra la decisión (append-only en el backend). Rechazar exige justificación. */
  async decide(candidateId: string, input: DecisionInput): Promise<void> {
    if (API_URL) {
      await http(`/candidates/${candidateId}/decision`, { method: "POST", body: JSON.stringify(input) });
      return;
    }
    await wait(250);
    const db = loadDb();
    const c = db.candidates.find((x) => x.id === candidateId);
    if (!c || c.status !== "pending_review") throw new ApiError("Solo se pueden decidir candidatas pendientes de revisión.", 409);
    c.status = input.decision;
    db.decisions.unshift({
      id: `dec_${Date.now()}`,
      candidate_id: candidateId,
      title: c.spec?.title ?? candidateId,
      decision: input.decision,
      justification: input.justification,
      review_time_ms: input.review_time_ms,
      at: new Date().toISOString(),
    });
    saveDb(db);
  },

  async listDecisions(runId: string): Promise<Decision[]> {
    if (API_URL) return http<Decision[]>(`/audit?run_id=${encodeURIComponent(runId)}`);
    await wait(150);
    return loadDb().decisions;
  },

  resetDemo() {
    localStorage.removeItem(KEY);
  },
};
