import { useEffect, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";
import { AlertTriangle, ArrowLeft, Check, ChevronRight, Eye, Inbox, Loader2, Search, X } from "lucide-react";
import { roleLabels } from "../api/admin";
import { useAuth } from "../auth";
import { combined, pct, relationLabels, requestLine, titleOf, transformationLabel } from "../api/format";
import type { HttpExchange, MRCandidate, RequestSpec } from "../api/types";
import { MethodBadge, ScoreBar, ScoreChip, StatusBadge, VerdictBadge, ErrorState } from "../components/ui";
import { useStore } from "../store";

type Filter = "pending_review" | "accepted" | "rejected" | "all";
const tabs: { id: Filter; label: string }[] = [
  { id: "pending_review", label: "Pendientes" },
  { id: "accepted", label: "Aceptadas" },
  { id: "rejected", label: "Rechazadas" },
  { id: "all", label: "Todas" },
];

function Req({ title, req, hint }: { title: string; req: Pick<RequestSpec, "path"> & Partial<RequestSpec>; hint?: string[] }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
      <div className="flex flex-wrap items-center gap-2 font-mono text-sm">
        <MethodBadge method={req.method ?? "GET"} />
        <span className="break-all">{requestLine(req)}</span>
      </div>
      {hint && hint.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-slate-600">
          {hint.map((h) => <li key={h}>• {h}</li>)}
        </ul>
      )}
    </div>
  );
}

function Exchange({ label, ex }: { label: string; ex: HttpExchange }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold text-slate-700">{label}</span>
        {ex.status_code != null && <span className={clsx("font-mono", ex.status_code >= 400 ? "text-red-700" : "text-emerald-700")}>HTTP {ex.status_code}</span>}
        {ex.elapsed_ms != null && <span className="text-slate-400">{Math.round(ex.elapsed_ms)} ms</span>}
        {ex.from_cache && <span className="rounded bg-slate-100 px-1.5 text-slate-500">caché</span>}
      </div>
      <p className="mt-1 break-all font-mono text-slate-500">{ex.url}</p>
      {ex.selected_excerpt && <pre className="mt-2 overflow-x-auto rounded bg-slate-900 p-2 font-mono text-slate-100">{ex.selected_excerpt}</pre>}
      {ex.error && <p className="mt-1 text-red-700">{ex.error}</p>}
    </div>
  );
}

function Evidence({ c }: { c: MRCandidate }) {
  const ex = c.execution;
  if (!ex) return null;
  return (
    <section aria-labelledby="ev" className="space-y-3 rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="ev" className="text-sm font-semibold">Resultado de la ejecución</h3>
        <VerdictBadge verdict={ex.verdict} />
      </div>
      {(ex.instances ?? []).map((i) => (
        <div key={i.index} className="space-y-2">
          {i.message && (
            <p className={clsx("flex gap-2 rounded-lg px-3 py-2 text-sm", i.verdict === "violation" ? "bg-red-50 text-red-800" : i.verdict === "error" ? "bg-amber-50 text-amber-900" : "bg-emerald-50 text-emerald-800")}>
              {i.verdict !== "pass" && <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />}
              {i.message}
            </p>
          )}
          <div className="grid gap-2 md:grid-cols-2">
            <Exchange label="Petición origen" ex={i.source} />
            {i.followups.map((f, n) => <Exchange key={n} label={`Petición derivada${i.followups.length > 1 ? ` ${n + 1}` : ""}`} ex={f} />)}
          </div>
        </div>
      ))}
    </section>
  );
}

function Detail({ c, onBack }: { c: MRCandidate; onBack: () => void }) {
  const { decide } = useStore();
  const { can, user } = useAuth();
  const spec = c.spec!;
  const [justification, setJustification] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const shownAt = useRef(Date.now());
  const area = useRef<HTMLTextAreaElement>(null);
  const decided = c.status !== "pending_review";

  useEffect(() => {
    setJustification("");
    setError("");
    shownAt.current = Date.now();
  }, [c.id]);

  async function submit(decision: "accepted" | "rejected") {
    const text = justification.trim();
    if (decision === "rejected" && !text) {
      setError("Explica por qué la rechazas: es obligatorio y queda en el registro de auditoría.");
      area.current?.focus();
      return;
    }
    setBusy(true);
    await decide(c.id, { decision, justification: text || undefined, review_time_ms: Date.now() - shownAt.current });
    setBusy(false);
  }

  const sem = c.scores?.semantic_validity;
  const fault = c.scores?.fault_revealing;

  return (
    <article key={c.id} className="animate-slide-in space-y-5 p-5 md:p-7">
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 lg:hidden">
        <ArrowLeft className="size-4" aria-hidden /> Volver a la lista
      </button>
      <header>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-slate-500">{c.id}</span>
          <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">{relationLabels[spec.relation.type] ?? spec.relation.type}</span>
          <StatusBadge status={c.status ?? "pending_review"} />
          {c.execution && <VerdictBadge verdict={c.execution.verdict} />}
        </div>
        <h2 className="text-xl font-bold leading-snug">{spec.title}</h2>
        <p className="mt-2 text-slate-600">{spec.description}</p>
      </header>

      <section className="grid gap-3 md:grid-cols-2">
        <Req title="Petición origen" req={spec.source} />
        {spec.followups.map((f, i) => (
          <Req
            key={i}
            title={`Petición derivada${spec.followups.length > 1 ? ` ${i + 1}` : ""}`}
            req={{ method: f.method ?? "GET", path: f.path ?? spec.source.path }}
            hint={(f.transformations ?? []).map(transformationLabel)}
          />
        ))}
      </section>

      <section className="rounded-xl border border-brand-100 bg-brand-50/60 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Relación esperada</p>
        <p className="mt-1 font-mono text-lg font-semibold text-brand-700">{spec.expected_relation}</p>
        <p className="mt-2 text-sm text-slate-600"><span className="font-medium text-slate-800">Transformación: </span>{spec.transformation_logic}</p>
        <p className="mt-1 text-sm text-slate-600"><span className="font-medium text-slate-800">Qué fallo podría revelar: </span>{spec.rationale}</p>
      </section>

      <Evidence c={c} />

      <section aria-label="Puntuaciones del filtro" className="space-y-3 rounded-xl border border-slate-200 p-4">
        <h3 className="text-sm font-semibold">Evaluación del filtro automático</h3>
        {sem && <ScoreBar label="Validez semántica" value={pct(sem.score)} reason={sem.llm_reason} />}
        {fault && <ScoreBar label="Potencial de encontrar fallos" value={pct(fault.score)} reason={fault.llm_reason} />}
        {c.scores?.max_similarity != null && (
          <p className="text-xs text-slate-500">Similitud máxima con otra MR: {pct(c.scores.max_similarity)}%</p>
        )}
      </section>

      <p className="text-xs text-slate-400">Generada por {c.provenance.model} · prompt {c.provenance.prompt_version}</p>

      {!decided && can.decide && (
        <section>
          <label htmlFor="just" className="mb-1.5 block text-sm font-medium">
            Justificación <span className="font-normal text-slate-500">(obligatoria al rechazar)</span>
          </label>
          <textarea
            id="just"
            ref={area}
            rows={3}
            value={justification}
            aria-invalid={!!error}
            aria-describedby={error ? "just-err" : undefined}
            onChange={(e) => { setJustification(e.target.value); setError(""); }}
            placeholder="Ej.: «Los resultados dependen del orden, esta relación no aplica»"
            className={clsx("w-full resize-none rounded-xl border bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2", error ? "border-red-400 focus:ring-red-500/20" : "border-slate-300 focus:border-brand-500 focus:ring-brand-500/20")}
          />
          {error && <p id="just-err" role="alert" className="mt-1 text-xs text-red-700">{error}</p>}
        </section>
      )}

      <div className="sticky bottom-0 -mx-5 flex flex-wrap items-center gap-3 border-t border-slate-200 bg-white/95 px-5 py-3 backdrop-blur md:-mx-7 md:px-7">
        {decided ? (
          <p className="text-sm text-slate-600">Esta decisión es definitiva y quedó registrada en la auditoría.</p>
        ) : !can.decide ? (
          <p className="flex items-center gap-2 text-sm text-slate-600"><Eye className="size-4" aria-hidden /> Modo lectura: como {user ? roleLabels[user.role] : "observador"} no puedes aceptar ni rechazar MRs.</p>
        ) : (
          <>
            <button disabled={busy} onClick={() => submit("accepted")} className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-emerald-700 disabled:opacity-60">
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Check className="size-4" aria-hidden />} Aceptar
            </button>
            <button disabled={busy} onClick={() => submit("rejected")} className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-2.5 text-sm font-semibold text-red-700 ring-1 ring-red-200 transition-colors hover:bg-red-50 disabled:opacity-60">
              <X className="size-4" aria-hidden /> Rechazar
            </button>
            <span className="ml-auto hidden text-xs text-slate-400 sm:block">J / K para cambiar de MR</span>
          </>
        )}
      </div>
    </article>
  );
}

export function Review() {
  const { candidates, run, loadError, reload } = useStore();
  const [filter, setFilter] = useState<Filter>("pending_review");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [mobileDetail, setMobileDetail] = useState(false);

  const reviewable = useMemo(() => candidates.filter((c) => c.status !== "discarded" && c.spec), [candidates]);
  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return reviewable
      .filter((c) => filter === "all" || c.status === filter)
      .filter((c) => !q || `${titleOf(c)} ${c.spec?.relation.type} ${c.id}`.toLowerCase().includes(q))
      .sort((a, b) => combined(b) - combined(a));
  }, [reviewable, filter, query]);

  const current = list.find((c) => c.id === selected) ?? list[0];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["TEXTAREA", "INPUT"].includes(t.tagName) || e.metaKey || e.ctrlKey) return;
      const i = current ? list.findIndex((c) => c.id === current.id) : -1;
      if (e.key === "j" && list[i + 1]) setSelected(list[i + 1].id);
      if (e.key === "k" && list[i - 1]) setSelected(list[i - 1].id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [list, current]);

  if (loadError) return <ErrorState message={loadError} onRetry={reload} />;
  const count = (f: Filter) => (f === "all" ? reviewable.length : reviewable.filter((c) => c.status === f).length);

  return (
    <div className="flex h-full">
      <section aria-label="Lista de MRs" className={clsx("flex w-full flex-col border-slate-200 bg-white lg:w-[400px] lg:shrink-0 lg:border-r", mobileDetail && "hidden lg:flex")}>
        <div className="space-y-3 border-b border-slate-200 p-4">
          <div>
            <h1 className="text-lg font-bold">Revisión de MRs</h1>
            <p className="text-xs text-slate-500">Ordenadas por puntuación combinada</p>
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
            <input type="search" aria-label="Buscar MRs" placeholder="Buscar por título o relación" value={query} onChange={(e) => setQuery(e.target.value)} className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20" />
          </div>
          <div role="tablist" aria-label="Filtrar por estado" className="flex gap-1 overflow-x-auto">
            {tabs.map((t) => (
              <button key={t.id} role="tab" aria-selected={filter === t.id} onClick={() => setFilter(t.id)} className={clsx("whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-colors", filter === t.id ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200")}>
                {t.label} <span className="opacity-70">{count(t.id)}</span>
              </button>
            ))}
          </div>
        </div>

        <ul className="min-h-0 flex-1 divide-y divide-slate-100 overflow-y-auto">
          {run?.status === "running" && (
            <li className="flex items-center gap-2 bg-brand-50 px-4 py-3 text-sm text-brand-700"><Loader2 className="size-4 animate-spin" aria-hidden /> Se están generando nuevas MRs…</li>
          )}
          {list.map((c) => (
            <li key={c.id}>
              <button onClick={() => { setSelected(c.id); setMobileDetail(true); }} aria-current={current?.id === c.id} className={clsx("flex w-full items-start gap-3 px-4 py-3.5 text-left transition-colors", current?.id === c.id ? "bg-brand-50" : "hover:bg-slate-50")}>
                <div className="min-w-0 flex-1">
                  <p className="mb-1 text-xs font-medium text-brand-700">{relationLabels[c.spec!.relation.type]}</p>
                  <p className="text-sm font-medium leading-snug">{titleOf(c)}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <StatusBadge status={c.status ?? "pending_review"} />
                    {c.execution?.verdict === "violation" && <VerdictBadge verdict="violation" />}
                    {c.execution?.verdict === "error" && <VerdictBadge verdict="error" />}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <ScoreChip value={combined(c)} />
                  <ChevronRight className="size-4 text-slate-300" aria-hidden />
                </div>
              </button>
            </li>
          ))}
          {list.length === 0 && (
            <li className="flex flex-col items-center gap-2 px-6 py-14 text-center text-slate-500">
              <Inbox className="size-8" aria-hidden />
              <p className="font-medium text-slate-700">{filter === "pending_review" && !query ? "¡Todo revisado!" : "Sin resultados"}</p>
              <p className="text-sm">{filter === "pending_review" && !query ? "Lanza una nueva iteración desde el resumen." : "Prueba con otro filtro o búsqueda."}</p>
            </li>
          )}
        </ul>
      </section>

      <section aria-label="Detalle de MR" className={clsx("min-w-0 flex-1 overflow-y-auto bg-white lg:bg-transparent", !mobileDetail && "hidden lg:block")}>
        {current ? (
          <div className="mx-auto max-w-3xl lg:my-6 lg:rounded-2xl lg:border lg:border-slate-200 lg:bg-white">
            <Detail c={current} onBack={() => setMobileDetail(false)} />
          </div>
        ) : (
          <div className="grid h-full place-items-center p-8 text-slate-500">Selecciona una MR para ver su detalle.</div>
        )}
      </section>
    </div>
  );
}
