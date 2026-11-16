import { formatUsd, runCost } from "../api/cost";
import { ArrowRight, Check, CircleAlert, Loader2, Sparkles, Circle } from "lucide-react";
import { clsx } from "clsx";
import { stageLabels } from "../api/format";
import { useAuth } from "../auth";
import { useStore } from "../store";

function Stat({ label, value, sub, tone }: { label: string; value: string | number; sub?: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5">
      <p className="text-sm text-slate-500">{label}</p>
      <p className={clsx("mt-1 text-3xl font-bold tabular-nums", tone)}>{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

const secs = (ms?: number | null) => (ms == null ? "" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);

export function Dashboard() {
  const { run, project, candidates, startRun, starting } = useStore();
  const { can } = useAuth();
  if (!run) {
    return (
      <div className="mx-auto max-w-xl animate-fade-up p-8 text-center">
        <Sparkles className="mx-auto size-10 text-brand-600" aria-hidden />
        <h1 className="mt-4 text-2xl font-bold">{project ? `${project.name} aún no tiene iteraciones` : "Elige un proyecto"}</h1>
        <p className="mt-2 text-slate-600">
          {can.launchRun
            ? "Lanza la primera iteración: el LLM propondrá relaciones metamórficas y las filtraremos para tu revisión."
            : "Cuando un auditor lance la primera iteración, podrás ver su trabajo aquí."}
        </p>
        <div className="mt-6 flex justify-center gap-3">
          {can.launchRun && project && (
            <button
              onClick={startRun}
              disabled={starting}
              className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {starting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Sparkles className="size-4" aria-hidden />} Lanzar iteración
            </button>
          )}
          <a href="#/proyectos" className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium hover:bg-slate-50">
            Ver proyectos
          </a>
        </div>
      </div>
    );
  }

  const by = (s: string) => candidates.filter((c) => c.status === s).length;
  const pending = by("pending_review");
  const accepted = by("accepted");
  const rejected = by("rejected");
  const discarded = by("discarded");
  const violations = candidates.filter((c) => c.status !== "discarded" && c.execution?.verdict === "violation").length;
  const confirmed = candidates.filter((c) => c.status === "accepted" && c.execution?.verdict === "violation").length;
  const acceptRate = accepted + rejected ? Math.round((accepted / (accepted + rejected)) * 100) : null;
  const tokens = run.report.stages.reduce((a, s) => a + (s.usage?.input_tokens ?? 0) + (s.usage?.output_tokens ?? 0), 0);
  const cost = runCost(run);
  const running = run.status === "running";
  const decided = accepted + rejected;

  return (
    <div className="mx-auto max-w-5xl animate-fade-up space-y-8 p-5 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-brand-700">
            Iteración {run.round} · {run.project_name ?? run.project_id}
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight md:text-3xl">Resumen del análisis</h1>
          <p className="mt-1 max-w-2xl text-slate-600">
            El LLM propone relaciones metamórficas, el filtro automático descarta las débiles y las ejecutamos contra tu API. Tú decides cuáles quedan.
          </p>
        </div>
        {can.launchRun && (
          <button
            onClick={startRun}
            disabled={running || starting}
            className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {running || starting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Sparkles className="size-4" aria-hidden />}
            {running ? "Ejecutando…" : "Nueva iteración"}
          </button>
        )}
      </header>

      {run.report.error && (
        <div role="alert" className="flex gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <CircleAlert className="size-5 shrink-0" aria-hidden />
          <div>
            <p className="font-semibold">La iteración falló</p>
            <p>{run.report.error}</p>
          </div>
        </div>
      )}
      {run.report.warnings.length > 0 && (
        <ul className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          {run.report.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <section aria-label="Métricas" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Pendientes de revisión" value={pending} sub={`${accepted} aceptadas · ${rejected} rechazadas`} tone="text-brand-700" />
        <Stat
          label="Fallos confirmados"
          value={confirmed}
          sub={`${violations} posibles · ${acceptRate == null ? "sin decisiones aún" : `${acceptRate}% de aceptación`}`}
          tone={confirmed ? "text-red-700" : undefined}
        />
        <Stat label="Descartadas por el filtro" value={discarded} sub="Se conservan con su motivo" />
        <Stat
          label="Tokens del LLM"
          value={tokens.toLocaleString("es")}
          sub={cost == null ? (run.report.generation_model ?? undefined) : `≈ ${formatUsd(cost)} · ${run.report.generation_model ?? ""}`}
        />
      </section>

      <section aria-labelledby="pipe">
        <h2 id="pipe" className="mb-3 text-lg font-semibold">
          Progreso del pipeline
        </h2>
        <ol className="divide-y divide-slate-100 overflow-hidden rounded-2xl border border-slate-200 bg-white">
          {run.report.stages.map((s) => (
            <li key={s.name} className="flex items-center gap-3 px-4 py-3">
              <span
                className={clsx(
                  "grid size-7 shrink-0 place-items-center rounded-full",
                  s.status === "done"
                    ? "bg-emerald-50 text-emerald-700"
                    : s.status === "running"
                      ? "bg-brand-50 text-brand-700"
                      : s.status === "failed"
                        ? "bg-red-50 text-red-700"
                        : "bg-slate-100 text-slate-400",
                )}
              >
                {s.status === "done" ? (
                  <Check className="size-4" aria-label="Completada" />
                ) : s.status === "running" ? (
                  <Loader2 className="size-4 animate-spin" aria-label="En curso" />
                ) : s.status === "failed" ? (
                  <CircleAlert className="size-4" aria-label="Fallida" />
                ) : (
                  <Circle className="size-3" aria-label={s.status === "skipped" ? "Omitida" : "Pendiente"} />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{stageLabels[s.name]}</p>
                {s.detail && <p className="truncate text-xs text-slate-500">{s.detail}</p>}
              </div>
              {s.input_count != null && s.output_count != null && (
                <span className="text-sm tabular-nums text-slate-600">
                  {s.input_count} → <strong>{s.output_count}</strong>
                </span>
              )}
              <span className="hidden w-16 text-right text-xs tabular-nums text-slate-400 sm:block">{secs(s.duration_ms)}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="flex flex-col items-start gap-4 rounded-2xl bg-gradient-to-br from-brand-600 to-violet-700 p-6 text-white md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-lg font-semibold">Revisión Human-in-the-Loop</h2>
          <p className="mt-1 max-w-xl text-sm text-indigo-100">
            {running
              ? "El pipeline está trabajando. Las candidatas aparecerán aquí cuando termine."
              : pending > 0
                ? can.decide
                  ? `Tienes ${pending} MRs esperando tu decisión. Tus justificaciones quedan registradas para la trazabilidad.`
                  : `Hay ${pending} MRs esperando la decisión de un auditor. Tienes acceso de solo lectura.`
                : decided > 0
                  ? "Revisaste todo. Lanza una nueva iteración para generar más MRs."
                  : "No hay candidatas por revisar."}
          </p>
        </div>
        <a
          href="#/revision"
          className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-brand-700 transition-colors hover:bg-indigo-50"
        >
          {can.decide ? "Revisar MRs" : "Ver MRs"} <ArrowRight className="size-4" aria-hidden />
        </a>
      </section>
    </div>
  );
}
