import { useState } from "react";
import { clsx } from "clsx";
import { reasonLabels, relationLabels, requestLine, titleOf } from "../api/format";
import { ErrorState } from "../components/ui";
import { useStore } from "../store";

export function Discarded() {
  const { candidates, loadError, reload } = useStore();
  const [reason, setReason] = useState<string>("all");
  if (loadError) return <ErrorState message={loadError} onRetry={reload} />;

  const all = candidates.filter((c) => c.status === "discarded");
  const list = all.filter((c) => reason === "all" || c.filter_result?.reason === reason);
  const reasons = Object.keys(reasonLabels);

  return (
    <div className="mx-auto max-w-3xl animate-fade-up space-y-6 p-5 md:p-8">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Descartadas por el filtro</h1>
        <p className="mt-1 text-slate-600">Son definitivas, pero puedes ver por qué se descartaron para confiar en el filtro.</p>
      </header>

      <div role="tablist" aria-label="Filtrar por motivo" className="flex gap-1.5 overflow-x-auto">
        {["all", ...reasons].map((r) => {
          const n = r === "all" ? all.length : all.filter((c) => c.filter_result?.reason === r).length;
          return (
            <button
              key={r}
              role="tab"
              aria-selected={reason === r}
              onClick={() => setReason(r)}
              className={clsx(
                "whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                reason === r ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200",
              )}
            >
              {r === "all" ? "Todas" : reasonLabels[r]} <span className="opacity-70">{n}</span>
            </button>
          );
        })}
      </div>

      {list.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          No hay candidatas descartadas con este motivo.
        </p>
      ) : (
        <ul className="space-y-3">
          {list.map((c) => (
            <li key={c.id} className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                  {reasonLabels[c.filter_result?.reason ?? ""] ?? "Descartada"}
                </span>
                {c.spec && <span className="text-xs text-brand-700">{relationLabels[c.spec.relation.type]}</span>}
                <span className="ml-auto font-mono text-xs text-slate-400">{c.id}</span>
              </div>
              <p className="mt-2 font-medium">{titleOf(c)}</p>
              {c.spec && <p className="mt-1 font-mono text-xs text-slate-500">GET {requestLine(c.spec.source)}</p>}
              <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{c.filter_result?.detail}</p>
              {c.filter_result?.duplicate_of && (
                <p className="mt-1 text-xs text-slate-500">
                  Redundante con <span className="font-mono">{c.filter_result.duplicate_of}</span>
                </p>
              )}
              {!c.spec && c.raw_output != null && (
                <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 font-mono text-xs text-slate-100">{JSON.stringify(c.raw_output, null, 2)}</pre>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
