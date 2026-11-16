import { useEffect, useState, type FormEvent } from "react";
import { clsx } from "clsx";
import { Loader2, Lock, Plus, Save } from "lucide-react";
import { roleHints, roleLabels, type LLMConfig, type PromptItem, type Role, type ThresholdSettings, type User } from "../api/admin";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth";
import { RoleBadge } from "../components/ui";
import { useStore } from "../store";

type Tab = "users" | "settings" | "prompts";
const tabs: { id: Tab; label: string }[] = [
  { id: "users", label: "Usuarios" },
  { id: "settings", label: "Modelo y umbrales" },
  { id: "prompts", label: "Prompts" },
];

const input =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20";
const msg = (e: unknown, fb: string) => (e instanceof ApiError ? e.message : fb);

// ───────────────────────────────── Usuarios ─────────────────────────────────

function Users() {
  const { user: me } = useAuth();
  const { notify } = useStore();
  const [users, setUsers] = useState<User[] | null>(null);
  const [form, setForm] = useState({ name: "", email: "", role: "qa" as Role, password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.listUsers().then(setUsers, (e) => notify(msg(e, "No se pudieron cargar los usuarios."), "error"));
  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function patch(u: User, change: Partial<Pick<User, "role" | "active">>) {
    try {
      const updated = await api.updateUser(u.id, change);
      setUsers((us) => us?.map((x) => (x.id === u.id ? updated : x)) ?? null);
      notify("Usuario actualizado");
    } catch (e) {
      notify(msg(e, "No se pudo actualizar el usuario."), "error");
    }
  }

  async function create(ev: FormEvent) {
    ev.preventDefault();
    if (form.name.trim().length < 2) return setError("Escribe el nombre de la persona.");
    if (!/^\S+@\S+\.\S+$/.test(form.email)) return setError("Escribe un correo válido.");
    if (form.password.length < 8) return setError("La contraseña temporal debe tener al menos 8 caracteres.");
    setError(null);
    setBusy(true);
    try {
      const u = await api.createUser({ ...form, name: form.name.trim() });
      setUsers((us) => [...(us ?? []), u]);
      setForm({ name: "", email: "", role: "qa", password: "" });
      notify(`Usuario ${u.name} creado`);
    } catch (e) {
      setError(msg(e, "No se pudo crear el usuario."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <section aria-label="Usuarios" className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        {!users ? (
          <p className="flex items-center gap-2 p-6 text-sm text-slate-500">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Cargando…
          </p>
        ) : (
          <table className="w-full min-w-[520px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <th scope="col" className="px-4 py-3 font-semibold">
                  Persona
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Rol
                </th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">
                  Activo
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((u) => {
                const self = u.id === me?.id;
                return (
                  <tr key={u.id} className={clsx(!u.active && "bg-slate-50 text-slate-400")}>
                    <td className="px-4 py-3">
                      <p className="font-medium">
                        {u.name}
                        {self && <span className="ml-2 text-xs font-normal text-slate-500">(tú)</span>}
                      </p>
                      <p className="text-xs text-slate-500">{u.email}</p>
                    </td>
                    <td className="px-4 py-3">
                      {self ? (
                        <RoleBadge role={u.role} />
                      ) : (
                        <select
                          aria-label={`Rol de ${u.name}`}
                          value={u.role}
                          onChange={(e) => patch(u, { role: e.target.value as Role })}
                          className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
                        >
                          {(Object.keys(roleLabels) as Role[]).map((r) => (
                            <option key={r} value={r}>
                              {roleLabels[r]}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        role="switch"
                        aria-checked={u.active}
                        aria-label={`${u.active ? "Desactivar" : "Activar"} a ${u.name}`}
                        disabled={self}
                        onClick={() => patch(u, { active: !u.active })}
                        title={self ? "No puedes desactivarte a ti mismo" : undefined}
                        className={clsx(
                          "relative h-6 w-11 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                          u.active ? "bg-emerald-500" : "bg-slate-300",
                        )}
                      >
                        <span className={clsx("absolute top-0.5 size-5 rounded-full bg-white shadow transition-all", u.active ? "left-[22px]" : "left-0.5")} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <form onSubmit={create} noValidate className="space-y-3 self-start rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="text-lg font-semibold">Nuevo usuario</h2>
        <div>
          <label htmlFor="un" className="mb-1 block text-sm font-medium">
            Nombre
          </label>
          <input id="un" className={input} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div>
          <label htmlFor="ue" className="mb-1 block text-sm font-medium">
            Correo
          </label>
          <input id="ue" type="email" className={input} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </div>
        <div>
          <label htmlFor="ur" className="mb-1 block text-sm font-medium">
            Rol
          </label>
          <select id="ur" className={input} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {(Object.keys(roleLabels) as Role[]).map((r) => (
              <option key={r} value={r}>
                {roleLabels[r]}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">{roleHints[form.role]}</p>
        </div>
        <div>
          <label htmlFor="up" className="mb-1 block text-sm font-medium">
            Contraseña temporal
          </label>
          <input
            id="up"
            type="password"
            autoComplete="new-password"
            className={input}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
          <p className="mt-1 text-xs text-slate-500">Mínimo 8 caracteres.</p>
        </div>
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
        <button
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Plus className="size-4" aria-hidden />} Crear usuario
        </button>
      </form>
    </div>
  );
}

// ──────────────────────────── Modelo y umbrales ────────────────────────────

function Num({
  id,
  label,
  hint,
  value,
  onChange,
  min,
  max,
  step,
}: {
  id: string;
  label: string;
  hint?: string;
  value: number;
  onChange: (n: number) => void;
  min: number;
  max: number;
  step: number;
}) {
  const bad = Number.isNaN(value) || value < min || value > max;
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={Number.isNaN(value) ? "" : value}
        aria-invalid={bad}
        onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))}
        className={clsx(input, bad && "border-red-400")}
      />
      <p className={clsx("mt-1 text-xs", bad ? "text-red-700" : "text-slate-500")}>{bad ? `Debe estar entre ${min} y ${max}.` : hint}</p>
    </div>
  );
}

function Settings() {
  const { notify } = useStore();
  const [t, setT] = useState<ThresholdSettings | null>(null);
  const [llm, setLLM] = useState<LLMConfig | null>(null);
  const [saving, setSaving] = useState<"t" | "l" | null>(null);

  useEffect(() => {
    Promise.all([api.getThresholds(), api.getLLM()]).then(
      ([a, b]) => {
        setT(a);
        setLLM(b);
      },
      (e) => notify(msg(e, "No se pudo cargar la configuración."), "error"),
    );
  }, [notify]);

  if (!t || !llm)
    return (
      <p className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Cargando…
      </p>
    );

  const tValid =
    [t.min_semantic, t.min_fault_revealing].every((v) => v >= 0 && v <= 1) &&
    t.similarity_threshold > 0 &&
    t.similarity_threshold <= 1 &&
    t.semantic_weight >= 0 &&
    t.fault_weight >= 0 &&
    t.semantic_weight + t.fault_weight > 0;
  const lValid = llm.max_candidates >= 1 && llm.max_candidates <= 50 && (llm.requests_per_minute == null || llm.requests_per_minute >= 1);

  async function save(kind: "t" | "l") {
    setSaving(kind);
    try {
      if (kind === "t") setT(await api.saveThresholds(t!));
      else setLLM(await api.saveLLM(llm!));
      notify("Configuración guardada: se aplica a las próximas iteraciones");
    } catch (e) {
      notify(msg(e, "No se pudo guardar."), "error");
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
        <div>
          <h2 className="text-lg font-semibold">Umbrales del filtro</h2>
          <p className="text-sm text-slate-600">Qué tan estricto es el filtro automático antes de llegar al auditor.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Num
            id="ms"
            label="Validez semántica mínima"
            hint="Por debajo se descarta (0–1)."
            value={t.min_semantic}
            onChange={(n) => setT({ ...t, min_semantic: n })}
            min={0}
            max={1}
            step={0.05}
          />
          <Num
            id="mf"
            label="Potencial de fallos mínimo"
            hint="Por debajo se descarta (0–1)."
            value={t.min_fault_revealing}
            onChange={(n) => setT({ ...t, min_fault_revealing: n })}
            min={0}
            max={1}
            step={0.05}
          />
          <Num
            id="sw"
            label="Peso de validez"
            hint="En la puntuación combinada."
            value={t.semantic_weight}
            onChange={(n) => setT({ ...t, semantic_weight: n })}
            min={0}
            max={10}
            step={0.1}
          />
          <Num
            id="fw"
            label="Peso de potencial de fallos"
            hint="En la puntuación combinada."
            value={t.fault_weight}
            onChange={(n) => setT({ ...t, fault_weight: n })}
            min={0}
            max={10}
            step={0.1}
          />
          <div className="sm:col-span-2">
            <Num
              id="st"
              label="Umbral de similitud (redundancia)"
              hint="Desde este coseno, una MR se considera repetida (0–1)."
              value={t.similarity_threshold}
              onChange={(n) => setT({ ...t, similarity_threshold: n })}
              min={0.01}
              max={1}
              step={0.005}
            />
          </div>
        </div>
        <button
          onClick={() => save("t")}
          disabled={!tValid || saving === "t"}
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving === "t" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />} Guardar umbrales
        </button>
      </section>

      <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
        <div>
          <h2 className="text-lg font-semibold">Modelo LLM</h2>
          <p className="text-sm text-slate-600">Las claves de API viven en el servidor, nunca aquí.</p>
        </div>
        <div className="space-y-4">
          <div>
            <label htmlFor="prov" className="mb-1 block text-sm font-medium">
              Proveedor
            </label>
            <select id="prov" className={input} value={llm.provider} onChange={(e) => setLLM({ ...llm, provider: e.target.value as LLMConfig["provider"] })}>
              <option value="anthropic">Anthropic</option>
              <option value="gemini">Gemini</option>
            </select>
            <p className="mt-1 text-xs text-slate-500">Si lo cambias, el servidor elige los modelos por defecto del proveedor salvo que los indiques.</p>
          </div>
          <div>
            <label htmlFor="gm" className="mb-1 block text-sm font-medium">
              Modelo de generación
            </label>
            <input
              id="gm"
              className={clsx(input, "font-mono")}
              value={llm.generation_model}
              onChange={(e) => setLLM({ ...llm, generation_model: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="vm" className="mb-1 block text-sm font-medium">
              Modelo de verificación
            </label>
            <input
              id="vm"
              className={clsx(input, "font-mono")}
              value={llm.verification_model}
              onChange={(e) => setLLM({ ...llm, verification_model: e.target.value })}
            />
          </div>
          <Num
            id="mc"
            label="MRs por iteración"
            hint="Controla el costo (1–50)."
            value={llm.max_candidates}
            onChange={(n) => setLLM({ ...llm, max_candidates: n })}
            min={1}
            max={50}
            step={1}
          />
          <Num
            id="rpm"
            label="Peticiones por minuto"
            hint="Límite del cliente; evita agotar la cuota."
            value={llm.requests_per_minute ?? NaN}
            onChange={(n) => setLLM({ ...llm, requests_per_minute: Number.isNaN(n) ? null : n })}
            min={1}
            max={10000}
            step={1}
          />
        </div>
        <button
          onClick={() => save("l")}
          disabled={!lValid || saving === "l"}
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving === "l" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />} Guardar modelo
        </button>
      </section>
    </div>
  );
}

// ─────────────────────────────────── Prompts ───────────────────────────────────

const kindLabels = { generation: "Generación", semantic: "Validez semántica", fault: "Potencial de fallos" } as const;

function Prompts() {
  const { notify } = useStore();
  const [items, setItems] = useState<PromptItem[] | null>(null);
  const [selId, setSelId] = useState<string | null>(null);
  const [draft, setDraft] = useState({ id: "", system: "", user: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listPrompts().then(
      (p) => {
        setItems(p);
        setSelId(p[0]?.id ?? null);
      },
      (e) => notify(msg(e, "No se pudieron cargar los prompts."), "error"),
    );
  }, [notify]);

  const sel = items?.find((p) => p.id === selId);
  useEffect(() => {
    if (sel) setDraft({ id: sel.editable ? sel.id : `${sel.id}_ed1`, system: sel.system, user: sel.user });
    setError(null);
  }, [selId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!items || !sel) return <p className="text-sm text-slate-500">{items ? "No hay prompts." : "Cargando…"}</p>;

  async function saveAsNew() {
    if (!/^[a-z0-9_]+$/.test(draft.id)) return setError("El id solo puede tener minúsculas, números y guion bajo.");
    if (items!.some((p) => p.id === draft.id)) return setError("Ese id ya existe. Usa uno nuevo para que la trazabilidad diga cuál se usó.");
    if (draft.system.trim().length < 10 || draft.user.trim().length < 5) return setError("El prompt está vacío o es demasiado corto.");
    setBusy(true);
    try {
      const created = await api.createPrompt({ id: draft.id, kind: sel!.kind, system: draft.system, user: draft.user });
      setItems((p) => [...(p ?? []), created]);
      setSelId(created.id);
      notify(`Prompt ${created.id} creado`);
    } catch (e) {
      setError(msg(e, "No se pudo guardar el prompt."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
      <ul className="space-y-1 self-start rounded-2xl border border-slate-200 bg-white p-2" aria-label="Prompts">
        {items.map((p) => (
          <li key={p.id}>
            <button
              onClick={() => setSelId(p.id)}
              aria-current={p.id === selId}
              className={clsx(
                "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm",
                p.id === selId ? "bg-brand-50 text-brand-700" : "hover:bg-slate-50",
              )}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono font-medium">{p.id}</span>
                <span className="block text-xs text-slate-500">{kindLabels[p.kind]}</span>
              </span>
              {!p.editable && <Lock className="size-3.5 shrink-0 text-slate-400" aria-label="Del repositorio, solo lectura" />}
            </button>
          </li>
        ))}
      </ul>
      <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
        <div>
          <h2 className="text-lg font-semibold">
            {kindLabels[sel.kind]} · <span className="font-mono">{sel.id}</span>
          </h2>
          <p className="text-sm text-slate-600">
            {sel.editable ? "Versión editada por un administrador." : "Prompt del repositorio: no se edita directamente. Crea una versión nueva con otro id."}
          </p>
        </div>
        <div>
          <label htmlFor="ps" className="mb-1 block text-sm font-medium">
            Sistema
          </label>
          <textarea
            id="ps"
            rows={5}
            className={clsx(input, "font-mono")}
            value={draft.system}
            readOnly={sel.editable}
            onChange={(e) => setDraft({ ...draft, system: e.target.value })}
          />
        </div>
        <div>
          <label htmlFor="pu" className="mb-1 block text-sm font-medium">
            Usuario
          </label>
          <textarea
            id="pu"
            rows={5}
            className={clsx(input, "font-mono")}
            value={draft.user}
            readOnly={sel.editable}
            onChange={(e) => setDraft({ ...draft, user: e.target.value })}
          />
        </div>
        {!sel.editable && (
          <div className="flex flex-wrap items-end gap-3 border-t border-slate-100 pt-4">
            <div className="min-w-[200px] flex-1">
              <label htmlFor="pid" className="mb-1 block text-sm font-medium">
                Id de la nueva versión
              </label>
              <input id="pid" className={clsx(input, "font-mono")} value={draft.id} onChange={(e) => setDraft({ ...draft, id: e.target.value })} />
            </div>
            <button
              onClick={saveAsNew}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />} Guardar como versión nueva
            </button>
          </div>
        )}
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
      </section>
    </div>
  );
}

// ─────────────────────────────────── Página ───────────────────────────────────

export function Admin() {
  const [tab, setTab] = useState<Tab>("users");
  return (
    <div className="mx-auto max-w-6xl animate-fade-up space-y-6 p-5 md:p-8">
      <header>
        <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Administración</h1>
        <p className="mt-1 text-slate-600">Usuarios y roles, configuración del modelo, umbrales del filtro y prompts.</p>
      </header>
      <div role="tablist" aria-label="Secciones de administración" className="flex gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
              tab === t.id ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">{tab === "users" ? <Users /> : tab === "settings" ? <Settings /> : <Prompts />}</div>
    </div>
  );
}
