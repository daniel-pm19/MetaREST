import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Project } from "./api/admin";
import { api, ApiError, DEFAULT_PROJECT_ID } from "./api/client";
import type { Decision, DecisionInput, Run } from "./api/run";
import type { MRCandidate } from "./api/types";

interface Toast {
  id: number;
  message: string;
  tone: "ok" | "error";
}

interface Store {
  projects: Project[];
  project: Project | null;
  runs: Run[];
  run: Run | null; // iteración seleccionada (por defecto, la más reciente)
  loaded: boolean;
  candidates: MRCandidate[];
  decisions: Decision[];
  loadError: string | null;
  starting: boolean;
  toast: Toast | null;
  selectProject: (id: string) => void;
  selectRun: (id: string | null) => void;
  decide: (id: string, input: DecisionInput) => Promise<boolean>;
  startRun: () => Promise<void>;
  reload: () => Promise<void>;
  notify: (message: string, tone?: Toast["tone"]) => void;
  resetDemo: () => Promise<void>;
  dismissToast: () => void;
}

const Ctx = createContext<Store | null>(null);
const PROJECT_KEY = "metarest-project";

export function StoreProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>(() => localStorage.getItem(PROJECT_KEY) ?? DEFAULT_PROJECT_ID);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<MRCandidate[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const timer = useRef<number>(undefined);

  const notify = useCallback((message: string, tone: Toast["tone"] = "ok") => {
    window.clearTimeout(timer.current);
    setToast({ id: Date.now(), message, tone });
    timer.current = window.setTimeout(() => setToast(null), tone === "error" ? 8000 : 4000);
  }, []);

  const reload = useCallback(async () => {
    try {
      const ps = await api.listProjects();
      const pid = ps.some((p) => p.id === projectId) ? projectId : (ps[0]?.id ?? projectId);
      // Sin proyectos registrados no hay nada que pedir (el id por defecto no existiría en el backend real).
      const rs = ps.length ? await api.listRuns(pid) : [];
      const latest = rs.find((r) => r.id === runId) ?? rs[rs.length - 1];
      const [cands, decs] = latest ? await Promise.all([api.listCandidates(latest.id), api.listDecisions(latest.id)]) : [[], []];
      setProjects(ps);
      if (pid !== projectId) setProjectId(pid);
      setRuns(rs);
      setCandidates(cands);
      setDecisions(decs);
      setLoadError(null);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setLoadError(e instanceof ApiError ? e.message : "Error inesperado al cargar los datos.");
    } finally {
      setLoaded(true);
    }
  }, [projectId, runId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const run = runs.find((r) => r.id === runId) ?? runs[runs.length - 1] ?? null;

  // Mientras el pipeline corre, consulta el progreso (docs/INTEGRATION.md §1.1).
  const running = run?.status === "running";
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(reload, 2000);
    return () => window.clearInterval(id);
  }, [running, reload]);

  const selectProject = useCallback((id: string) => {
    localStorage.setItem(PROJECT_KEY, id);
    setLoaded(false);
    setRunId(null);
    setProjectId(id);
  }, []);

  const selectRun = useCallback((id: string | null) => setRunId(id), []);

  const decide: Store["decide"] = useCallback(
    async (id, input) => {
      try {
        await api.decide(id, input);
        setCandidates((cs) => cs.map((c) => (c.id === id ? { ...c, status: input.decision } : c)));
        if (run)
          api
            .listDecisions(run.id)
            .then(setDecisions)
            .catch(() => {});
        notify(input.decision === "accepted" ? "MR aceptada" : "MR rechazada");
        return true;
      } catch (e) {
        notify(e instanceof ApiError ? e.message : "No se pudo guardar la decisión.", "error");
        if (e instanceof ApiError && e.status === 409) reload();
        return false;
      }
    },
    [notify, reload, run],
  );

  const startRun = useCallback(async () => {
    setStarting(true);
    try {
      await api.startRun(projectId);
      setRunId(null);
      await reload();
      notify("Iteración en curso: puede tardar unos minutos");
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "No se pudo iniciar la iteración.", "error");
    } finally {
      setStarting(false);
    }
  }, [projectId, reload, notify]);

  const resetDemo = useCallback(async () => {
    api.resetDemo();
    await reload();
    notify("Datos de demostración restablecidos");
  }, [reload, notify]);

  const project = projects.find((p) => p.id === projectId) ?? null;
  const value = useMemo<Store>(
    () => ({
      projects,
      project,
      runs,
      run,
      loaded,
      candidates,
      decisions,
      loadError,
      starting,
      toast,
      selectProject,
      selectRun,
      decide,
      startRun,
      reload,
      notify,
      resetDemo,
      dismissToast: () => setToast(null),
    }),
    [
      projects,
      project,
      runs,
      run,
      loaded,
      candidates,
      decisions,
      loadError,
      starting,
      toast,
      selectProject,
      selectRun,
      decide,
      startRun,
      reload,
      notify,
      resetDemo,
    ],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStore fuera de StoreProvider");
  return v;
}
