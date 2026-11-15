import { clsx } from "clsx";
import { AlertTriangle, Check, CircleCheck, Clock, X } from "lucide-react";
import type { CandidateStatus, Verdict } from "../api/types";

type Method = "GET" | "HEAD" | "POST" | "PUT" | "PATCH" | "DELETE";
const methodColors: Record<string, string> = {
  GET: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  HEAD: "bg-sky-50 text-sky-700 ring-sky-600/20",
};

export function MethodBadge({ method }: { method: Method }) {
  return (
    <span className={clsx("rounded-md px-1.5 py-0.5 font-mono text-[11px] font-semibold ring-1 ring-inset", methodColors[method] ?? "bg-slate-100 text-slate-700 ring-slate-500/20")}>
      {method}
    </span>
  );
}

const statusMap: Record<CandidateStatus, { label: string; cls: string; Icon: typeof Check }> = {
  pending_review: { label: "Pendiente", cls: "bg-slate-100 text-slate-700", Icon: Clock },
  accepted: { label: "Aceptada", cls: "bg-emerald-50 text-emerald-700", Icon: Check },
  rejected: { label: "Rechazada", cls: "bg-red-50 text-red-700", Icon: X },
  discarded: { label: "Descartada", cls: "bg-slate-100 text-slate-500", Icon: X },
};

export function StatusBadge({ status }: { status: CandidateStatus }) {
  const { label, cls, Icon } = statusMap[status];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", cls)}>
      <Icon className="size-3" aria-hidden /> {label}
    </span>
  );
}

const verdictMap: Record<Verdict, { label: string; cls: string; Icon: typeof Check }> = {
  pass: { label: "Se cumple", cls: "bg-emerald-50 text-emerald-700", Icon: CircleCheck },
  violation: { label: "Posible fallo", cls: "bg-red-100 text-red-700", Icon: AlertTriangle },
  error: { label: "Error al ejecutar", cls: "bg-amber-50 text-amber-800", Icon: AlertTriangle },
  skipped: { label: "No ejecutada", cls: "bg-slate-100 text-slate-600", Icon: Clock },
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const { label, cls, Icon } = verdictMap[verdict];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold", cls)}>
      <Icon className="size-3" aria-hidden /> {label}
    </span>
  );
}

export function scoreTone(v: number) {
  return v >= 85 ? "emerald" : v >= 70 ? "amber" : "red";
}

const bar = { emerald: "bg-emerald-500", amber: "bg-amber-500", red: "bg-red-500" };
const text = { emerald: "text-emerald-700", amber: "text-amber-700", red: "text-red-700" };

export function ScoreBar({ label, value, reason }: { label: string; value: number; reason?: string | null }) {
  const tone = scoreTone(value);
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span className="text-slate-600">{label}</span>
        <span className={clsx("font-semibold tabular-nums", text[tone])}>{value}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100" role="meter" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
        <div className={clsx("h-full rounded-full transition-[width] duration-500", bar[tone])} style={{ width: `${value}%` }} />
      </div>
      {reason && <p className="mt-1 text-xs text-slate-500">{reason}</p>}
    </div>
  );
}

export function ScoreChip({ value }: { value: number }) {
  const tone = scoreTone(value);
  const cls = { emerald: "bg-emerald-50 text-emerald-700", amber: "bg-amber-50 text-amber-800", red: "bg-red-50 text-red-700" }[tone];
  return (
    <span className={clsx("rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums", cls)} title="Puntuación combinada (0–100)">
      {value}
    </span>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
      <AlertTriangle className="mx-auto size-8 text-red-600" aria-hidden />
      <p className="mt-3 font-semibold text-red-900">No pudimos cargar los datos</p>
      <p className="mt-1 text-sm text-red-800">{message}</p>
      <button onClick={onRetry} className="mt-4 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700">
        Reintentar
      </button>
    </div>
  );
}
