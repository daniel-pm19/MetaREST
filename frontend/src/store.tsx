import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError, PROJECT_ID, RUN_ID } from "./api/client";
import type { Decision, DecisionInput, Run } from "./api/run";
import type { MRCandidate } from "./api/types";

interface Toast {
  id: number;
  message: string;
  tone: "ok" | "error";
}

interface Store {
  run: Run | null;
  candidates: MRCandidate[];
  decisions: Decision[];
  loadError: string | null;
  starting: boolean;
  toast: Toast | null;
  decide: (id: string, input: DecisionInput) => Promise<boolean>;
  startRun: () => Promise<void>;
  reload: () => Promise<void>;
  resetDemo: () => Promise<void>;
  dismissToast: () => void;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [run, setRun] = useState<Run | null>(null);
  const [candidates, setCandidates] = useState<MRCandidate[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const timer = useRef<number>(undefined);
  const runId = useRef(RUN_ID);

  const showToast = useCallback((message: string, tone: Toast["tone"] = "ok") => {
    window.clearTimeout(timer.current);
    setToast({ id: Date.now(), message, tone });
    timer.current = window.setTimeout(() => setToast(null), tone === "error" ? 8000 : 4000);
  }, []);

  const reload = useCallback(async () => {
    try {
      const r = await api.getRun(runId.current);
      runId.current = r.id;
      const [cands, decs] = await Promise.all([api.listCandidates(r.id), api.listDecisions(r.id)]);
      setRun(r);
      setCandidates(cands);
      setDecisions(decs);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Error inesperado al cargar los datos.");
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  // Mientras el pipeline corre, consulta el progreso (docs/INTEGRATION.md §1.1).
  const running = run?.status === "running";
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(reload, 2000);
    return () => window.clearInterval(id);
  }, [running, reload]);

  const decide: Store["decide"] = useCallback(
    async (id, input) => {
      try {
        await api.decide(id, input);
        setCandidates((cs) => cs.map((c) => (c.id === id ? { ...c, status: input.decision } : c)));
        api.listDecisions(runId.current).then(setDecisions).catch(() => {});
        showToast(input.decision === "accepted" ? "MR aceptada" : "MR rechazada");
        return true;
      } catch (e) {
        showToast(e instanceof ApiError ? e.message : "No se pudo guardar la decisión.", "error");
        if (e instanceof ApiError && e.status === 409) reload();
        return false;
      }
    },
    [showToast, reload],
  );

  const startRun = useCallback(async () => {
    setStarting(true);
    try {
      const r = await api.startRun(PROJECT_ID);
      runId.current = r.id;
      setRun(r);
      showToast("Iteración en curso: puede tardar unos minutos");
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : "No se pudo iniciar la iteración.", "error");
    } finally {
      setStarting(false);
    }
  }, [showToast]);

  const resetDemo = useCallback(async () => {
    api.resetDemo();
    runId.current = RUN_ID;
    await reload();
    showToast("Datos de demostración restablecidos");
  }, [reload, showToast]);

  const value = useMemo<Store>(
    () => ({ run, candidates, decisions, loadError, starting, toast, decide, startRun, reload, resetDemo, dismissToast: () => setToast(null) }),
    [run, candidates, decisions, loadError, starting, toast, decide, startRun, reload, resetDemo],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStore fuera de StoreProvider");
  return v;
}
