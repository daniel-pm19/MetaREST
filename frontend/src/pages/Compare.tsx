import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { ArrowDown, ArrowUp, GitCompare, Loader2, Minus } from "lucide-react";
import type { RunMetrics } from "../api/admin";
import { api, ApiError } from "../api/client";
import { useStore } from "../store";

interface Row {
  label: string;
  value: (m: RunMetrics) => number | null;
  fmt: (v: number) => string;
  better?: "up" | "down"; // qué dirección es positiva en el cambio
}

const dur = (ms: number) => (ms < 60000 ? `${Math.round(ms / 1000)} s` : `${(ms / 60000).toFixed(1)} min`);
const rows: Row[] = [
  { label: "Candidatas generadas", value: (m) => m.generated, fmt: String },
  { label: "Descartadas por el filtro", value: (m) => m.discarded, fmt: String },
  { label: "Posibles fallos (violaciones)", value: (m) => m.violations, fmt: String },
  { label: "Fallos confirmados por el auditor", value: (m) => m.confirmed_faults, fmt: String, better: "up" },
  { label: "Tasa de aceptación", value: (m) => (m.acceptance_rate == null ? null : m.acceptance_rate * 100), fmt: (v) => `${Math.round(v)} %`, better: "up" },
  { label: "Puntuación media", value: (m) => m.avg_combined, fmt: String, better: "up" },
  { label: "Tokens usados", value: (m) => m.tokens, fmt: (v) => v.toLocaleString("es"), better: "down" },
  { label: "Tiempo medio de revisión", value: (m) => m.avg_review_ms, fmt: dur, better: "down" },
];

function Delta({ a, b, row }: { a: number | null; b: number | null; row: Row }) {
  if (a == null || b == null) return <span className="text-slate-400">—</span>;
  const d = b - a;
  if (d === 0) return <span className="inline-flex items-center gap-1 text-slate-500"><Minus className="size-3" aria-hidden /> Sin cambio</span>;
  const good = row.better ? (d > 0) === (row.better === "up") : null;
  const Icon = d > 0 ? ArrowUp : ArrowDown;
  return (
    <span className={clsx("inline-flex items-center gap-1 font-medium tabular-nums", good == null ? "text-slate-600" : good ? "text-emerald-700" : "text-red-700")}>
      <Icon className="size-3" aria-hidden />
      {d > 0 ? "+" : "−"}{row.fmt(Math.abs(d))}
      <span className="sr-only">{good == null ? "" : good ? " (mejora)" : " (empeora)"}</span>
    </span>
  );
}

export function Compare() {
  const { runs, project } = useStore();
  const [selected, setSelected] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<RunMetrics[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const finished = runs.filter((r) => r.status !== "running");
  useEffect(() => setSelected(finished.slice(-2).map((r) => r.id)), [runs.length]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (selected.length < 2) return setMetrics([]);
    setLoading(true);
    setError(null);
    api.compareRuns(selected).then(setMetrics, (e) => setError(e instanceof ApiError ? e.message : "No se pudieron cargar las métricas.")).finally(() => setLoading(false));
  }, [selected]);

  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id].slice(-4)));
  const ordered = selected.map((id) => metrics.find((m) => m.run_id === id)).filter((m): m is RunMetrics => !!m);

  return (
    <div className="mx-auto max-w-5xl animate-fade-up space-y-6 p-5 md:p-8">
      <header>
        <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Comparar iteraciones</h1>
        <p className="mt-1 text-slate-600">Mide si cada nueva iteración de {project?.name ?? "tu API"} mejora la calidad de las MRs.</p>
      </header>

      {finished.length < 2 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <GitCompare className="mx-auto size-9 text-slate-400" aria-hidden />
          <p className="mt-3 font-semibold">Necesitas al menos 2 iteraciones terminadas</p>
          <p className="mt-1 text-sm text-slate-600">Hoy hay {finished.length}. Lanza una nueva iteración desde el resumen para poder compararlas.</p>
          <a href="#/resumen" className="mt-4 inline-block rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">Ir al resumen</a>
        </div>
      ) : (
        <>
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Iteraciones a comparar <span className="font-normal text-slate-500">(2 a 4)</span></legend>
            <div className="flex flex-wrap gap-2">
              {finished.map((r) => (
                <label key={r.id} className={clsx("cursor-pointer rounded-full border px-3 py-1.5 text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-brand-600", selected.includes(r.id) ? "border-brand-600 bg-brand-50 font-medium text-brand-700" : "border-slate-300 bg-white text-slate-600 hover:border-slate-400")}>
                  <input type="checkbox" className="sr-only" checked={selected.includes(r.id)} onChange={() => toggle(r.id)} />
                  Iteración {r.round}
                </label>
              ))}
            </div>
          </fieldset>

          {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          {selected.length < 2 && <p className="text-sm text-slate-500">Elige al menos dos iteraciones.</p>}
          {loading && <p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="size-4 animate-spin" aria-hidden /> Calculando…</p>}

          {ordered.length >= 2 && !loading && (
            <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <th scope="col" className="px-4 py-3 font-semibold">Métrica</th>
                    {ordered.map((m) => <th key={m.run_id} scope="col" className="px-4 py-3 text-right font-semibold">Iteración {m.round}</th>)}
                    {ordered.length === 2 && <th scope="col" className="px-4 py-3 text-right font-semibold">Cambio</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {rows.map((row) => (
                    <tr key={row.label}>
                      <th scope="row" className="px-4 py-3 font-medium text-slate-700">{row.label}</th>
                      {ordered.map((m) => {
                        const v = row.value(m);
                        return <td key={m.run_id} className="px-4 py-3 text-right tabular-nums">{v == null ? <span className="text-slate-400">—</span> : row.fmt(v)}</td>;
                      })}
                      {ordered.length === 2 && <td className="px-4 py-3 text-right"><Delta a={row.value(ordered[0])} b={row.value(ordered[1])} row={row} /></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
