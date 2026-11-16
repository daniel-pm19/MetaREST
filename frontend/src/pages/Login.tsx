import { useState, type FormEvent } from "react";
import { Eye, EyeOff, Loader2, ShieldCheck, Sparkles, Eye as EyeIcon, ClipboardCheck } from "lucide-react";
import { roleHints, roleLabels, type Role } from "../api/admin";
import { ApiError, demoAccounts, isMock } from "../api/client";
import { useAuth } from "../auth";

const roleIcon = { admin: ShieldCheck, qa: ClipboardCheck, observer: EyeIcon } as const;

export function Login() {
  const { login, notice } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function attempt(e: string, p: string) {
    setError(null);
    setBusy(true);
    try {
      await login(e, p);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo iniciar sesión. Inténtalo de nuevo.");
      setBusy(false);
    }
  }

  function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    if (!email.trim() || !password) {
      setError("Escribe tu correo y tu contraseña.");
      return;
    }
    attempt(email, password);
  }

  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-gradient-to-br from-brand-600 via-brand-700 to-violet-800 p-12 text-white lg:flex">
        <div className="flex items-center gap-3">
          <div className="grid size-10 place-items-center rounded-xl bg-white/15">
            <Sparkles className="size-5" aria-hidden />
          </div>
          <span className="text-xl font-bold">MetaREST</span>
        </div>
        <div>
          <h2 className="max-w-md text-4xl font-bold leading-tight tracking-tight">Encuentra fallos de lógica sin conocer la respuesta exacta.</h2>
          <p className="mt-4 max-w-md text-indigo-100">
            Un LLM propone relaciones metamórficas para tu API REST, un filtro automático se queda con las mejores y tú decides cuáles usar.
          </p>
        </div>
        <p className="text-sm text-indigo-200">Testing metamórfico con humano en el ciclo</p>
      </div>

      <main className="flex items-center justify-center p-6 md:p-12">
        <div className="w-full max-w-sm animate-fade-up">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-violet-600 text-white">
              <Sparkles className="size-5" aria-hidden />
            </div>
            <span className="text-lg font-bold">MetaREST</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Inicia sesión</h1>
          <p className="mt-1 text-sm text-slate-600">Accede con tu cuenta para revisar las relaciones metamórficas.</p>

          {notice && (
            <p role="status" className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {notice}
            </p>
          )}

          <form onSubmit={onSubmit} noValidate className="mt-6 space-y-4">
            <div>
              <label htmlFor="email" className="mb-1.5 block text-sm font-medium">
                Correo
              </label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="tu@correo.com"
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1.5 block text-sm font-medium">
                Contraseña
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={show ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white py-2.5 pl-3 pr-10 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
                />
                <button
                  type="button"
                  onClick={() => setShow((s) => !s)}
                  aria-label={show ? "Ocultar contraseña" : "Mostrar contraseña"}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-slate-500 hover:text-slate-800"
                >
                  {show ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
                </button>
              </div>
            </div>
            {error && (
              <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700 disabled:opacity-60"
            >
              {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} Entrar
            </button>
          </form>

          {isMock && (
            <section aria-label="Acceso de demostración" className="mt-8 border-t border-slate-200 pt-6">
              <p className="text-sm font-medium">Modo demostración</p>
              <p className="mb-3 text-xs text-slate-500">Entra con un rol de ejemplo para ver qué puede hacer cada uno.</p>
              <div className="space-y-2">
                {demoAccounts.map((a) => {
                  const Icon = roleIcon[a.role as Role];
                  return (
                    <button
                      key={a.role}
                      type="button"
                      disabled={busy}
                      onClick={() => attempt(a.email, a.password)}
                      className="flex w-full items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left transition-colors hover:border-brand-500 hover:bg-brand-50/50 disabled:opacity-60"
                    >
                      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700">
                        <Icon className="size-4" aria-hidden />
                      </span>
                      <span>
                        <span className="block text-sm font-semibold">{roleLabels[a.role]}</span>
                        <span className="block text-xs text-slate-500">{roleHints[a.role]}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
