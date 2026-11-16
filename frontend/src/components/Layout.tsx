import { LayoutDashboard, ListChecks, Trash2, History, GitCompare, FolderKanban, Settings2, Sparkles, RotateCcw, LogOut, type LucideIcon } from "lucide-react";
import { clsx } from "clsx";
import type { ReactNode } from "react";
import { isMock } from "../api/client";
import { useAuth } from "../auth";
import { useStore } from "../store";
import { RoleBadge } from "./ui";

export type Route = "resumen" | "revision" | "descartadas" | "decisiones" | "comparar" | "proyectos" | "admin";

interface Item {
  id: Route;
  label: string;
  short: string;
  Icon: LucideIcon;
  allowed: (c: ReturnType<typeof useAuth>["can"]) => boolean;
}

export const navItems: Item[] = [
  { id: "resumen", label: "Resumen", short: "Resumen", Icon: LayoutDashboard, allowed: () => true },
  { id: "revision", label: "Revisión de MRs", short: "Revisión", Icon: ListChecks, allowed: () => true },
  { id: "descartadas", label: "Descartadas", short: "Descartadas", Icon: Trash2, allowed: () => true },
  { id: "decisiones", label: "Decisiones", short: "Decisiones", Icon: History, allowed: () => true },
  { id: "comparar", label: "Comparar iteraciones", short: "Comparar", Icon: GitCompare, allowed: () => true },
  { id: "proyectos", label: "Proyectos", short: "Proyectos", Icon: FolderKanban, allowed: () => true },
  { id: "admin", label: "Administración", short: "Admin", Icon: Settings2, allowed: (c) => c.admin },
];

export function Layout({ route, children }: { route: Route; children: ReactNode }) {
  const { project, runs, run, selectRun, candidates, resetDemo, toast, dismissToast } = useStore();
  const { user, can, logout } = useAuth();
  const pending = candidates.filter((c) => c.status === "pending_review").length;
  const items = navItems.filter((i) => i.allowed(can));

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
        <nav aria-label="Principal" className="flex-1 space-y-1 overflow-y-auto px-3">
          {items.map(({ id, label, Icon }) => (
            <a
              key={id}
              href={`#/${id}`}
              aria-current={route === id ? "page" : undefined}
              className={clsx("flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors", route === id ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}
            >
              <Icon className="size-[18px]" aria-hidden />
              {label}
              {id === "revision" && pending > 0 && <span className="ml-auto rounded-full bg-brand-600 px-2 py-0.5 text-xs font-semibold text-white">{pending}</span>}
            </a>
          ))}
        </nav>
        <div className="space-y-2 border-t border-slate-200 p-3">
          <a href="#/proyectos" className="block rounded-lg px-3 py-1.5 hover:bg-slate-50" title="Cambiar de proyecto">
            <span className="block text-[11px] uppercase tracking-wide text-slate-400">Proyecto activo</span>
            <span className="block truncate text-sm font-medium">{project?.name ?? "—"}</span>
          </a>
          {runs.length > 1 && run && (
            <label className="block px-3">
              <span className="block text-[11px] uppercase tracking-wide text-slate-400">Iteración</span>
              <select
                value={run.id}
                onChange={(e) => selectRun(e.target.value === runs[runs.length - 1].id ? null : e.target.value)}
                className="mt-0.5 w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm"
              >
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    Iteración {r.round}
                    {r.id === runs[runs.length - 1].id ? " (actual)" : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          {isMock && (
            <div className="flex items-center justify-between px-3">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
                <span className="size-1.5 rounded-full bg-amber-500" aria-hidden /> Demo
              </span>
              <button onClick={resetDemo} className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800">
                <RotateCcw className="size-3" aria-hidden /> Restablecer
              </button>
            </div>
          )}
          {user && (
            <div className="flex items-center gap-2 rounded-xl bg-slate-50 p-2.5">
              <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-brand-600 text-sm font-semibold text-white">{user.name.charAt(0).toUpperCase()}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{user.name}</p>
                <RoleBadge role={user.role} />
              </div>
              <button onClick={logout} aria-label="Cerrar sesión" title="Cerrar sesión" className="rounded-lg p-2 text-slate-500 hover:bg-white hover:text-slate-900">
                <LogOut className="size-4" aria-hidden />
              </button>
            </div>
          )}
        </div>
      </aside>

      <header className="flex items-center gap-2 border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <div className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-violet-600 text-white">
          <Sparkles className="size-4" aria-hidden />
        </div>
        <span className="font-bold">MetaREST</span>
        {user && <span className="ml-auto"><RoleBadge role={user.role} /></span>}
        <button onClick={logout} aria-label="Cerrar sesión" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><LogOut className="size-4" aria-hidden /></button>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>

      <nav aria-label="Principal" className="flex overflow-x-auto border-t border-slate-200 bg-white md:hidden">
        {items.map(({ id, short, Icon }) => (
          <a key={id} href={`#/${id}`} aria-current={route === id ? "page" : undefined} className={clsx("flex min-w-[72px] flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium", route === id ? "text-brand-700" : "text-slate-500")}>
            <Icon className="size-5" aria-hidden />
            {short}
          </a>
        ))}
      </nav>

      {toast && (
        <div role={toast.tone === "error" ? "alert" : "status"} className={clsx("animate-fade-up fixed bottom-20 left-1/2 z-50 flex max-w-[90vw] -translate-x-1/2 items-center gap-3 rounded-xl px-4 py-3 text-sm text-white shadow-xl md:bottom-6", toast.tone === "error" ? "bg-red-700" : "bg-slate-900")}>
          {toast.message}
          <button onClick={dismissToast} className="font-semibold underline-offset-2 hover:underline">Cerrar</button>
        </div>
      )}
    </div>
  );
}
