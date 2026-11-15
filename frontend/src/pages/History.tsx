import { Check, MessageSquareText, X } from "lucide-react";
import { useStore } from "../store";

const fmt = (iso: string) => new Date(iso).toLocaleString("es", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const dur = (ms?: number | null) => (ms == null ? null : ms < 60000 ? `${Math.round(ms / 1000)} s` : `${Math.round(ms / 60000)} min`);

export function HistoryPage() {
  const { decisions } = useStore();

  return (
    <div className="mx-auto max-w-3xl animate-fade-up space-y-6 p-5 md:p-8">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Decisiones y trazabilidad</h1>
        <p className="mt-1 text-slate-600">Registro inmutable de lo que aceptaste o rechazaste, con tu justificación y el tiempo de revisión.</p>
      </header>

      {decisions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <MessageSquareText className="mx-auto size-9 text-slate-400" aria-hidden />
          <p className="mt-3 font-semibold">Aún no hay decisiones</p>
          <p className="mt-1 text-sm text-slate-600">Acepta o rechaza MRs para que queden registradas.</p>
          <a href="#/revision" className="mt-4 inline-block rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">Ir a revisar</a>
        </div>
      ) : (
        <ol className="space-y-3">
          {decisions.map((d) => (
            <li key={d.id} className="flex gap-3 rounded-xl border border-slate-200 bg-white p-4">
              <div className={`grid size-8 shrink-0 place-items-center rounded-full ${d.decision === "accepted" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
                {d.decision === "accepted" ? <Check className="size-4" aria-label="Aceptada" /> : <X className="size-4" aria-label="Rechazada" />}
              </div>
              <div className="min-w-0 flex-1">
                <p className="font-medium">{d.title}</p>
                {d.justification && <p className="mt-1 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">«{d.justification}»</p>}
                <p className="mt-1.5 text-xs text-slate-500">
                  {d.user && <>por <strong className="font-medium text-slate-700">{d.user}</strong> · </>}
                  <span className="font-mono">{d.candidate_id}</span> · {fmt(d.at)}
                  {dur(d.review_time_ms) && ` · revisada en ${dur(d.review_time_ms)}`}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
