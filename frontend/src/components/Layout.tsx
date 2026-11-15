import { LayoutDashboard, ListChecks, Trash2, History, Sparkles, RotateCcw, type LucideIcon } from "lucide-react";
import { clsx } from "clsx";
import type { ReactNode } from "react";
import { isMock } from "../api/client";
import { useStore } from "../store";

export type Route = "resumen" | "revision" | "descartadas" | "decisiones";

const items: { id: Route; label: string; short: string; Icon: LucideIcon }[] = [
  { id: "resumen", label: "Resumen", short: "Resumen", Icon: LayoutDashboard },
  { id: "revision", label: "Revisión de MRs", short: "Revisión", Icon: ListChecks },
  { id: "descartadas", label: "Descartadas", short: "Descartadas", Icon: Trash2 },
  { id: "decisiones", label: "Decisiones", short: "Decisiones", Icon: History },
];

export function Layout({ route, children }: { route: Route; children: ReactNode }) {
  const { run, candidates, resetDemo, toast, dismissToast } = useStore();
  const pending = candidates.filter((c) => c.status === "pending_review").length;

  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-violet-600 text-white shadow-sm">
            <Sparkles className="size-5" aria-hidden />
          </div>
          <div>
            <p className="text-base font-bold leading-tight">MetaREST</p>
            <p className="text-xs text-slate-500">Testing metamórfico</p>
          </div>
        </div>
        <nav aria-label="Principal" className="flex-1 space-y-1 px-3">
          {items.map(({ id, label, Icon }) => (
            <a
              key={id}
              href={`#/${id}`}
              aria-current={route === id ? "page" : undefined}
              className={clsx(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                route === id ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
              )}
            >
              <Icon className="size-[18px]" aria-hidden />
              {label}
              {id === "revision" && pending > 0 && (
                <span className="ml-auto rounded-full bg-brand-600 px-2 py-0.5 text-xs font-semibold text-white">{pending}</span>
              )}
            </a>
          ))}
        </nav>
        <div className="space-y-1 border-t border-slate-200 p-3">
          <p className="truncate px-3 text-xs text-slate-500" title={run?.project_id}>
            {run?.project_name ?? run?.project_id ?? "—"}
          </p>
          <p className="px-3 pb-1 text-xs">
            <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-medium", isMock ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-700")}>
              <span className={clsx("size-1.5 rounded-full", isMock ? "bg-amber-500" : "bg-emerald-500")} aria-hidden />
              {isMock ? "Datos de demostración" : "Conectado al backend"}
            </span>
          </p>
          {isMock && (
            <button onClick={resetDemo} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-800">
              <RotateCcw className="size-4" aria-hidden /> Restablecer demo
            </button>
          )}
        </div>
      </aside>

      <header className="flex items-center gap-2 border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <div className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-violet-600 text-white">
          <Sparkles className="size-4" aria-hidden />
        </div>
        <span className="font-bold">MetaREST</span>
        {isMock && <span className="ml-auto rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">Demo</span>}
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>

      <nav aria-label="Principal" className="grid grid-cols-4 border-t border-slate-200 bg-white md:hidden">
        {items.map(({ id, short, Icon }) => (
          <a key={id} href={`#/${id}`} aria-current={route === id ? "page" : undefined} className={clsx("flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium", route === id ? "text-brand-700" : "text-slate-500")}>
            <Icon className="size-5" aria-hidden />
            {short}
          </a>
        ))}
      </nav>

      {toast && (
        <div
          role={toast.tone === "error" ? "alert" : "status"}
          className={clsx("animate-fade-up fixed bottom-20 left-1/2 z-50 flex max-w-[90vw] -translate-x-1/2 items-center gap-3 rounded-xl px-4 py-3 text-sm text-white shadow-xl md:bottom-6", toast.tone === "error" ? "bg-red-700" : "bg-slate-900")}
        >
          {toast.message}
          <button onClick={dismissToast} className="font-semibold underline-offset-2 hover:underline">
            Cerrar
          </button>
        </div>
      )}
    </div>
  );
}
