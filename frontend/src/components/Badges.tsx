import { useI18n } from "../i18n";
import type { IncidentStatus, InvestigationStatus, Priority, Severity, SlaState, Source } from "../types/incident";

const base = "inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold whitespace-nowrap";

const SEVERITY: Record<Severity, string> = {
  P1: "bg-red-600 text-white",
  P2: "bg-orange-500 text-white",
  P3: "bg-amber-200 text-amber-900",
  P4: "bg-slate-200 text-slate-700",
};

const SLA: Record<SlaState, string> = {
  ON_TRACK: "bg-emerald-100 text-emerald-800",
  AT_RISK: "bg-amber-100 text-amber-800",
  BREACHED: "bg-red-100 text-red-800",
  MET: "bg-sky-100 text-sky-800",
};

const STATUS: Record<IncidentStatus, string> = {
  OPEN: "bg-slate-100 text-slate-800",
  ASSIGNED: "bg-indigo-100 text-indigo-800",
  INVESTIGATING: "bg-blue-100 text-blue-800",
  ESCALATED: "bg-red-100 text-red-800",
  ON_HOLD: "bg-amber-100 text-amber-800",
  RESOLVED: "bg-emerald-100 text-emerald-800",
  CLOSED: "bg-slate-200 text-slate-600",
  REOPENED: "bg-orange-100 text-orange-800",
};

const INVESTIGATION: Record<InvestigationStatus, string> = {
  PENDING: "bg-slate-100 text-slate-700",
  RUNNING: "bg-blue-100 text-blue-800",
  AWAITING_REVIEW: "bg-amber-100 text-amber-800",
  APPROVED: "bg-emerald-100 text-emerald-800",
  REJECTED: "bg-slate-200 text-slate-700",
  FAILED: "bg-red-100 text-red-800",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`${base} ${SEVERITY[severity]}`}>{severity}</span>;
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  const { label } = useI18n();
  return <span className={`${base} bg-white text-slate-700 ring-1 ring-slate-300`}>{label(priority)}</span>;
}

export function StatusBadge({ status }: { status: IncidentStatus }) {
  const { label } = useI18n();
  return <span className={`${base} ${STATUS[status]}`}>{label(status)}</span>;
}

export function SlaBadge({ state }: { state: SlaState }) {
  const { label } = useI18n();
  return <span className={`${base} ${SLA[state]}`}>{label(state)}</span>;
}

export function InvestigationBadge({ status }: { status: InvestigationStatus }) {
  const { label } = useI18n();
  return (
    <span className={`${base} ${INVESTIGATION[status]}`}>
      {status === "RUNNING" && <span className="mr-1.5 h-1.5 w-1.5 animate-pulse rounded-full bg-blue-600" />}
      {label(status)}
    </span>
  );
}

export function SourceBadge({ source }: { source: Source }) {
  const { label } = useI18n();
  const style = source === "AI" ? "bg-violet-100 text-violet-800" : source === "SYSTEM" ? "bg-slate-100 text-slate-600" : "bg-teal-100 text-teal-800";
  return <span className={`${base} ${style}`}>{label(source)}</span>;
}
