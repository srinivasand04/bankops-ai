import {
  Brain, ChevronRight, ClipboardList, Gauge, GitCommitHorizontal, Loader2, Network, ShieldCheck, Workflow, Wrench,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import type { AgentExecution, AgentFinding, Calculation, Investigation } from "../types/incident";
import { Card } from "./ui";

const AGENTS: Record<string, { title: string; icon: LucideIcon; job: string }> = {
  triage: { title: "Triage", icon: ClipboardList, job: "Symptoms, timing, severity and SLA" },
  supervisor: { title: "Supervisor", icon: Workflow, job: "Decides which specialists the incident needs" },
  change_release: { title: "Change & release", icon: GitCommitHorizontal, job: "Deployments close to the start of impact" },
  dependency_impact: { title: "Dependency & impact", icon: Network, job: "Blast radius across connected applications" },
  operational_risk: { title: "Operational risk", icon: Gauge, job: "Change risk, recurrence, SLA exposure" },
  root_cause: { title: "Root cause", icon: Brain, job: "Combines the findings into the report" },
};
const SPECIALISTS = ["change_release", "dependency_impact", "operational_risk"];

type NodeState = "done" | "running" | "failed" | "waiting" | "review" | "approved" | "rejected";

const NODE_STYLE: Record<NodeState, string> = {
  done: "bg-emerald-50 text-emerald-800 ring-emerald-300",
  running: "bg-blue-50 text-blue-800 ring-blue-400",
  failed: "bg-red-50 text-red-800 ring-red-300",
  waiting: "bg-slate-50 text-slate-400 ring-slate-200 border-dashed",
  review: "bg-amber-50 text-amber-900 ring-amber-400",
  approved: "bg-emerald-50 text-emerald-800 ring-emerald-300",
  rejected: "bg-red-50 text-red-800 ring-red-300",
};
const RISK_STYLE = { LOW: "bg-slate-100 text-slate-700", MEDIUM: "bg-amber-100 text-amber-800", HIGH: "bg-red-100 text-red-800" };

export function isAgentRun(inv: Investigation) {
  return inv.agents_selected?.includes("supervisor");
}

function stateOf(step: AgentExecution | undefined): NodeState {
  if (!step) return "waiting";
  return step.status === "COMPLETED" ? "done" : step.status === "RUNNING" ? "running" : step.status === "FAILED" ? "failed" : "waiting";
}

function seconds(step: AgentExecution, now: number) {
  const end = step.completed_at ? new Date(step.completed_at).getTime() : now;
  return Math.max(0, Math.round((end - new Date(step.started_at).getTime()) / 1000));
}

function duration(s: number) {
  return s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}

function Ids({ ids }: { ids: string[] }) {
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {ids.map((x) => <code key={x} className="rounded bg-slate-100 px-1 text-xs text-slate-600">{x}</code>)}
    </span>
  );
}

/** The agent team: who ran, in what order, which tools they called and what they found. */
export default function AgentTeam({ inv }: { inv: Investigation }) {
  const [now, setNow] = useState(Date.now());
  const running = inv.status === "RUNNING";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [running]);

  const byName = Object.fromEntries(inv.executions.map((e) => [e.agent_name, e]));
  const planned = inv.agents_selected.filter((a) => SPECIALISTS.includes(a));
  const planned_known = !!byName.supervisor && byName.supervisor.status === "COMPLETED";
  const skipped = planned_known ? SPECIALISTS.filter((a) => !planned.includes(a)) : [];
  const flow = ["triage", "supervisor", ...(planned_known ? planned : ["?"]), "root_cause"];
  const human: NodeState = inv.status === "APPROVED" ? "approved" : inv.status === "REJECTED" ? "rejected"
    : inv.status === "AWAITING_REVIEW" ? "review" : "waiting";
  const tokens = inv.executions.reduce((n, e) => n + (e.input_tokens ?? 0) + (e.output_tokens ?? 0), 0);
  const findings = inv.report?.agent_findings ?? {};

  return (
    <Card
      title={<span className="flex items-center gap-2"><Workflow size={16} aria-hidden="true" /> Agent team (LangGraph)</span>}
      actions={<span className="text-xs text-slate-500">{inv.executions.length} step{inv.executions.length === 1 ? "" : "s"}{tokens > 0 && ` · ${tokens.toLocaleString()} tokens`}</span>}
    >
      {/* flow strip */}
      <div className="flex flex-wrap items-center gap-1.5">
        {flow.map((name, n) => {
          const meta = AGENTS[name];
          const st = name === "?" ? "waiting" : stateOf(byName[name]);
          const Icon = meta?.icon ?? Workflow;
          return (
            <div key={`${name}-${n}`} className="flex items-center gap-1.5">
              {n > 0 && <ChevronRight size={14} className="text-slate-400" aria-hidden="true" />}
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${NODE_STYLE[st]}`}>
                {st === "running" ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Icon size={13} aria-hidden="true" />}
                {meta?.title ?? "specialists…"}
              </span>
            </div>
          );
        })}
        <ChevronRight size={14} className="text-slate-400" aria-hidden="true" />
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${NODE_STYLE[human]}`}>
          <ShieldCheck size={13} aria-hidden="true" /> Human review
        </span>
      </div>
      {skipped.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">Not needed for this incident (supervisor's choice): {skipped.map((s) => AGENTS[s].title).join(", ")}</p>
      )}

      {/* steps */}
      <ol className="mt-4 space-y-3">
        {inv.executions.map((step) => {
          const meta = AGENTS[step.agent_name] ?? { title: step.agent_name, icon: Workflow, job: "" };
          const Icon = meta.icon;
          const st = stateOf(step);
          const finding = (findings[step.agent_name] ?? step.output?.finding) as AgentFinding | undefined;
          return (
            <li key={step.step_order} className={`rounded-md p-3 ring-1 ${st === "running" ? "bg-blue-50/50 ring-blue-200" : st === "failed" ? "bg-red-50/50 ring-red-200" : "ring-slate-200"}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-navy-900 text-xs font-semibold text-white">{step.step_order}</span>
                <Icon size={16} className="text-navy-800" aria-hidden="true" />
                <b className="font-semibold text-navy-900">{meta.title}</b>
                <span className="text-xs text-slate-500">{meta.job}</span>
                <span className="ml-auto flex items-center gap-2 text-xs text-slate-500">
                  {st === "running" && <Loader2 size={13} className="animate-spin text-blue-700" aria-hidden="true" />}
                  <span className={st === "failed" ? "font-medium text-red-700" : st === "running" ? "font-medium text-blue-800" : ""}>
                    {st === "running" ? "working" : step.status.toLowerCase()} · {duration(seconds(step, now))}
                  </span>
                  {step.input_tokens != null && <span>{step.input_tokens} in / {step.output_tokens} out</span>}
                </span>
              </div>

              {step.tool_calls.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-8">
                  <Wrench size={12} className="text-slate-400" aria-hidden="true" />
                  {step.tool_calls.map((t) => (
                    <code key={t.tool} className="rounded bg-violet-50 px-1.5 py-0.5 text-xs text-violet-800 ring-1 ring-violet-200"
                      title={t.result ? JSON.stringify(t.result) : undefined}>
                      {t.tool}{t.ms != null && <span className="text-violet-500"> {t.ms} ms</span>}
                    </code>
                  ))}
                </div>
              )}

              <div className="pl-8">
                {step.agent_name === "supervisor" && step.output && (
                  <div className="mt-2 text-sm text-slate-700">
                    <p>{String(step.output.reasoning ?? "")}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      Plan: {(step.output.plan as string[] | undefined)?.length
                        ? (step.output.plan as string[]).map((p) => AGENTS[p]?.title ?? p).join(" → ")
                        : "no specialists needed, straight to root cause"}
                    </p>
                  </div>
                )}
                {finding && (
                  <div className="mt-2 text-sm">
                    <p className="text-slate-800">
                      <span className={`mr-2 rounded px-1.5 py-0.5 text-xs font-semibold ${RISK_STYLE[finding.risk_signal]}`}>{finding.risk_signal}</span>
                      {finding.summary}
                    </p>
                    {finding.findings.length > 0 && (
                      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-slate-700">
                        {finding.findings.map((f, n) => <li key={n}>{f.statement}<Ids ids={f.evidence_ids} /></li>)}
                      </ul>
                    )}
                    {finding.open_questions.length > 0 && (
                      <p className="mt-1.5 text-xs text-slate-500">Open questions: {finding.open_questions.join(" · ")}</p>
                    )}
                  </div>
                )}
                {step.agent_name === "root_cause" && st === "done" && inv.report && (
                  <p className="mt-2 text-sm text-slate-700">
                    Wrote the report below: {inv.report.root_cause_hypotheses.length} hypotheses, {inv.report.recommended_actions.length} recommended
                    actions, overall confidence {inv.report.overall_confidence}. Guardrails then checked it.
                  </p>
                )}
                {step.error_message && <p className="mt-2 text-sm text-red-700">{step.error_message}</p>}
              </div>
            </li>
          );
        })}
        {running && (
          <li className="rounded-md border border-dashed border-slate-300 p-3 text-xs text-slate-500">
            Next steps appear here as the supervisor routes the work. Hosted models finish in about a minute; a local model can take 10-20 minutes.
          </li>
        )}
      </ol>

      <Calculations calc={inv.report?.calculations} />
    </Card>
  );
}

function Calculations({ calc }: { calc?: { impact?: Calculation; risk?: Calculation } }) {
  const items = [calc?.impact && ["Incident impact", calc.impact], calc?.risk && ["Operational risk", calc.risk]].filter(Boolean) as [string, Calculation][];
  if (!items.length) return null;
  return (
    <div className="mt-4 grid gap-3 sm:grid-cols-2">
      {items.map(([label, c]) => (
        <div key={c.id} className="rounded-md bg-slate-50 p-3">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-navy-900">{label} <code className="text-xs text-slate-500">{c.id}</code></span>
            <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${RISK_STYLE[c.band]}`}>{c.score}/100 {c.band}</span>
          </div>
          <div className="mt-2 h-1.5 rounded bg-slate-200">
            <div className={`h-1.5 rounded ${c.band === "HIGH" ? "bg-red-500" : c.band === "MEDIUM" ? "bg-amber-500" : "bg-slate-500"}`} style={{ width: `${c.score}%` }} />
          </div>
          {c.components && (
            <p className="mt-1.5 text-xs text-slate-600">
              {Object.entries(c.components).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(" · ")}
            </p>
          )}
          <p className="mt-1 text-xs text-slate-500">{c.method}</p>
        </div>
      ))}
    </div>
  );
}

export type AnalysisMode = "single" | "agents";

/** Choose between the one-call analysis and the LangGraph agent team. */
export function ModePicker({ mode, onChange, agentsLeft }: { mode: AnalysisMode; onChange: (m: AnalysisMode) => void; agentsLeft?: number | null }) {
  const options: { value: AnalysisMode; label: string; hint: string }[] = [
    { value: "single", label: "Single AI call", hint: "fastest: one call with the full fact base" },
    { value: "agents", label: "Agent team", hint: `triage, supervisor, specialists, root cause${agentsLeft != null ? ` · ${agentsLeft} left today` : ""}` },
  ];
  return (
    <div role="radiogroup" aria-label="Analysis mode" className="grid gap-2 sm:grid-cols-2">
      {options.map((o) => (
        <label key={o.value} className={`flex cursor-pointer items-start gap-2 rounded-md p-2 text-sm ring-1 ${mode === o.value ? "bg-navy-900/5 ring-navy-800" : "ring-slate-200 hover:bg-slate-50"}`}>
          <input type="radio" name="analysis-mode" className="mt-1" checked={mode === o.value} onChange={() => onChange(o.value)} />
          <span><b className="font-medium text-navy-900">{o.label}</b><span className="block text-xs text-slate-500">{o.hint}</span></span>
        </label>
      ))}
    </div>
  );
}
