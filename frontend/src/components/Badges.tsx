import type { IncidentStatus, Severity, SlaState } from "../types/incident";

const SEVERITY_STYLES: Record<Severity, string> = {
  P1: "bg-red-600 text-white",
  P2: "bg-orange-500 text-white",
  P3: "bg-amber-200 text-amber-900",
  P4: "bg-slate-200 text-slate-700",
};

const SLA_STYLES: Record<SlaState, string> = {
  ON_TRACK: "bg-emerald-100 text-emerald-800",
  AT_RISK: "bg-amber-100 text-amber-800",
  BREACHED: "bg-red-100 text-red-800",
  MET: "bg-sky-100 text-sky-800",
};

const base = "inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold whitespace-nowrap";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`${base} ${SEVERITY_STYLES[severity]}`}>{severity}</span>;
}

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return <span className={`${base} bg-navy-900/10 text-navy-900`}>{status.replace("_", " ")}</span>;
}

export function SlaBadge({ state }: { state: SlaState }) {
  return <span className={`${base} ${SLA_STYLES[state]}`}>{state.replace("_", " ")}</span>;
}
