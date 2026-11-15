import { useRef, useState, type FormEvent } from "react";
import { clsx } from "clsx";
import { Check, FileUp, Loader2, Plus } from "lucide-react";
import type { NewProject } from "../api/admin";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth";
import { useStore } from "../store";

const MAX_BYTES = 2 * 1024 * 1024;
const fmtDate = (iso: string) => new Date(iso).toLocaleDateString("es", { day: "2-digit", month: "short", year: "numeric" });

function NewProjectForm({ onDone }: { onDone: (id: string) => void }) {
  const { reload, notify } = useStore();
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [spec, setSpec] = useState<{ name: string; text: string } | null>(null);
  const [errors, setErrors] = useState<Partial<Record<"name" | "url" | "spec" | "form", string>>>({});
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function onFile(file?: File) {
    if (!file) return;
    if (!/\.(json|ya?ml)$/i.test(file.name)) return setErrors((e) => ({ ...e, spec: "Sube un archivo .json, .yaml o .yml." }));
    if (file.size > MAX_BYTES) return setErrors((e) => ({ ...e, spec: "El archivo supera los 2 MB." }));
    setSpec({ name: file.name, text: await file.text() });
    setErrors((e) => ({ ...e, spec: undefined }));
  }

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    const next: typeof errors = {};
    if (name.trim().length < 3) next.name = "Escribe un nombre de al menos 3 caracteres.";
    try {
      const u = new URL(baseUrl);
      if (!/^https?:$/.test(u.protocol)) throw new Error();
    } catch {
      next.url = "Escribe una URL válida, por ejemplo https://api.miapp.com";
    }
    if (!spec) next.spec = "Sube la especificación OpenAPI de tu API.";
    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    const payload: NewProject = { name: name.trim(), base_url: baseUrl.trim().replace(/\/$/, ""), openapi: spec!.text };
    try {
      const p = await api.createProject(payload);
      notify(`Proyecto «${p.name}» registrado`);
      await reload();
      onDone(p.id);
    } catch (e) {
      setErrors({ form: e instanceof ApiError ? e.message : "No se pudo registrar el proyecto." });
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded-lg border bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2";
  const ok = "border-slate-300 focus:border-brand-500 focus:ring-brand-500/20";
  const bad = "border-red-400 focus:ring-red-500/20";

  return (
    <form onSubmit={submit} noValidate className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">Registrar una API</h2>
      <div>
        <label htmlFor="pname" className="mb-1.5 block text-sm font-medium">Nombre</label>
        <input id="pname" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!errors.name} className={clsx(field, errors.name ? bad : ok)} placeholder="Tienda online" />
        {errors.name && <p role="alert" className="mt-1 text-xs text-red-700">{errors.name}</p>}
      </div>
      <div>
        <label htmlFor="purl" className="mb-1.5 block text-sm font-medium">URL base de la API</label>
        <input id="purl" inputMode="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} aria-invalid={!!errors.url} className={clsx(field, errors.url ? bad : ok)} placeholder="https://api.miapp.com" />
        <p className="mt-1 text-xs text-slate-500">MetaREST solo hace peticiones GET y HEAD a esta URL.</p>
        {errors.url && <p role="alert" className="mt-1 text-xs text-red-700">{errors.url}</p>}
      </div>
      <div>
        <span className="mb-1.5 block text-sm font-medium">Especificación OpenAPI</span>
        <input ref={fileRef} type="file" accept=".json,.yaml,.yml" className="sr-only" id="pspec" onChange={(e) => onFile(e.target.files?.[0])} />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files[0]); }}
          className={clsx("flex w-full flex-col items-center gap-1 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors hover:border-brand-500 hover:bg-brand-50/40", errors.spec ? "border-red-400" : spec ? "border-emerald-400 bg-emerald-50/40" : "border-slate-300")}
        >
          {spec ? <Check className="size-6 text-emerald-600" aria-hidden /> : <FileUp className="size-6 text-slate-400" aria-hidden />}
          <span className="text-sm font-medium">{spec ? spec.name : "Arrastra tu archivo o haz clic para elegirlo"}</span>
          <span className="text-xs text-slate-500">{spec ? "Haz clic para cambiarlo" : "JSON o YAML · máx. 2 MB"}</span>
        </button>
        {errors.spec && <p role="alert" className="mt-1 text-xs text-red-700">{errors.spec}</p>}
      </div>
      {errors.form && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{errors.form}</p>}
      <button type="submit" disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700 disabled:opacity-60">
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Plus className="size-4" aria-hidden />} Registrar proyecto
      </button>
    </form>
  );
}

export function Projects() {
  const { projects, project, selectProject } = useStore();
  const { can } = useAuth();

  return (
    <div className="mx-auto max-w-5xl animate-fade-up space-y-8 p-5 md:p-8">
      <header>
        <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Proyectos</h1>
        <p className="mt-1 text-slate-600">Cada proyecto es una API REST con su especificación OpenAPI. Elige en cuál trabajar.</p>
      </header>

      <div className={clsx("grid gap-6", can.manageProjects && "lg:grid-cols-[1fr_380px]")}>
        <section aria-label="Proyectos registrados">
          <ul className="space-y-3">
            {projects.map((p) => {
              const active = p.id === project?.id;
              return (
                <li key={p.id} className={clsx("flex flex-wrap items-center gap-4 rounded-2xl border bg-white p-4", active ? "border-brand-500 ring-1 ring-brand-500" : "border-slate-200")}>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">{p.name}</p>
                    <p className="truncate font-mono text-xs text-slate-500">{p.base_url}</p>
                    <p className="mt-1 text-xs text-slate-500">{p.endpoints != null && `${p.endpoints} endpoints GET · `}registrado el {fmtDate(p.created_at)}</p>
                  </div>
                  {active ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700"><Check className="size-3" aria-hidden /> Activo</span>
                  ) : (
                    <button onClick={() => selectProject(p.id)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium transition-colors hover:border-brand-500 hover:text-brand-700">Abrir</button>
                  )}
                </li>
              );
            })}
            {projects.length === 0 && <li className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">Aún no hay proyectos.{can.manageProjects ? " Registra tu primera API." : ""}</li>}
          </ul>
        </section>
        {can.manageProjects && <NewProjectForm onDone={selectProject} />}
      </div>
    </div>
  );
}
