import { AlertTriangle, ArrowLeft, Check, Loader2, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { InvestigationBadge, SeverityBadge } from "../components/Badges";
import { Button, Card, ErrorBanner, Field, formatTime, inputClass } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { aiApi, errorMessage } from "../services/api";
import { canAct, type Identity } from "../services/identity";
import type { AnalysisReport, Investigation } from "../types/incident";

export default function InvestigationDetailPage({ identity }: { identity: Identity }) {
  const id = Number(useParams().id);
  // Poll every 5 s while the AI is still working
  const inv = useApi(() => aiApi.get(id), [id], { pollMs: 5000, keepPolling: (d) => !d || d.status === "RUNNING" });

  if (inv.error) return <ErrorBanner message={inv.error} />;
  const d = inv.data;
  if (!d) return <p className="text-sm text-slate-500">Loading…</p>;

  return (
    <div className="space-y-4">
      <Link to="/investigations" className="inline-flex items-center gap-1 text-sm text-slate-600 hover:underline">
        <ArrowLeft size={14} aria-hidden="true" /> AI investigations
      </Link>

      <div className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-slate-500">INV-{d.id}</span>
          <InvestigationBadge status={d.status} />
          {d.incident_id && (
            <Link to={`/incidents/${d.incident_id}`} className="text-sm text-navy-800 hover:underline">{d.incident_reference}</Link>
          )}
        </div>
        <h1 className="mt-2 text-lg font-semibold text-navy-900">{d.request_text}</h1>
        <p className="mt-1 text-sm text-slate-500">
          Requested by {d.requested_by} · {formatTime(d.created_at)}
          {d.model_name && ` · ${d.model_name}`}
          {d.executions[0]?.output_tokens != null && ` · ${d.executions[0].input_tokens} in / ${d.executions[0].output_tokens} out tokens`}
        </p>
      </div>

      {d.status === "RUNNING" && <Running startedAt={d.created_at} />}
      {d.status === "FAILED" && <ErrorBanner message={`Analysis failed: ${d.error_message}`} />}
      {d.report && <Report report={d.report} />}
      {d.report && <ReviewPanel investigation={d} identity={identity} onReviewed={inv.reload} />}
    </div>
  );
}

function Running({ startedAt }: { startedAt: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  const seconds = Math.max(0, Math.round((now - new Date(startedAt).getTime()) / 1000));
  return (
    <div className="flex items-center gap-3 rounded-lg bg-blue-50 p-4 text-sm text-blue-900 ring-1 ring-blue-200">
      <Loader2 size={20} className="animate-spin" aria-hidden="true" />
      <div>
        <p className="font-medium">The AI is analysing the incident… {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}</p>
        <p className="text-blue-800">A local model takes about 5-12 minutes; Claude under a minute. This page refreshes by itself.</p>
      </div>
    </div>
  );
}

function List({ items }: { items: string[] }) {
  return <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{items.map((x, n) => <li key={n}>{x}</li>)}</ul>;
}

function Ids({ ids }: { ids: string[] }) {
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {ids.map((x) => <code key={x} className="rounded bg-slate-100 px-1 text-xs text-slate-600">{x}</code>)}
    </span>
  );
}

function Report({ report: r }: { report: AnalysisReport }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Card title="Summary">
          <p className="text-sm leading-relaxed text-slate-800">{r.summary}</p>
          <p className="mt-3 text-xs text-slate-500">Overall confidence: {r.overall_confidence}. {r.disclaimer}</p>
        </Card>

        <Card title="Root cause hypotheses (not confirmed)">
          <ol className="space-y-3">
            {r.root_cause_hypotheses.map((h, n) => (
              <li key={n} className="rounded-md bg-slate-50 p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-medium text-slate-600">#{n + 1} · {h.category.replaceAll("_", " ")}</span>
                  <span className="text-xs font-semibold text-slate-700">{Math.round(h.confidence * 100)}%</span>
                </div>
                <div className="mt-1 h-1.5 rounded bg-slate-200">
                  <div className="h-1.5 rounded bg-violet-600" style={{ width: `${Math.round(h.confidence * 100)}%` }} />
                </div>
                <p className="mt-2 text-sm text-slate-800">{h.description}</p>
                {h.supporting_evidence_ids.length > 0 && <p className="mt-1 text-xs text-slate-600">Supported by<Ids ids={h.supporting_evidence_ids} /></p>}
                {h.contradicting_evidence_ids.length > 0 && <p className="mt-1 text-xs text-slate-600">Contradicted by<Ids ids={h.contradicting_evidence_ids} /></p>}
                {h.verification_steps.length > 0 && <p className="mt-1 text-xs text-slate-600">Verify: {h.verification_steps.join("; ")}</p>}
              </li>
            ))}
          </ol>
        </Card>

        <Card title="Confirmed facts (cited)">
          <ul className="space-y-2 text-sm text-slate-700">
            {r.confirmed_facts.map((f, n) => <li key={n}>{f.statement}<Ids ids={f.evidence_ids} /></li>)}
          </ul>
          {r.unverified_statements.length > 0 && (
            <div className="mt-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
              <p className="font-medium">Removed from facts - no valid evidence:</p>
              <List items={r.unverified_statements} />
            </div>
          )}
        </Card>

        <Card title="Recommended actions">
          <ul className="divide-y divide-slate-100">
            {r.recommended_actions.map((a, n) => (
              <li key={n} className="py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium text-slate-700">{a.action_type}</span>
                  <span className="text-slate-500">{a.urgency.replace("_", " ")}</span>
                  <span className="text-slate-500">{a.owner_team}</span>
                  {a.requires_human_approval && (
                    <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800">
                      <AlertTriangle size={12} aria-hidden="true" /> needs approval
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-slate-800">{a.description}</p>
                {a.approval_reason && <p className="text-xs text-slate-500">{a.approval_reason}</p>}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="space-y-4">
        <Card title="Business impact">
          <div className="mb-2 flex items-center gap-2 text-sm">Assessed severity <SeverityBadge severity={r.business_impact.assessed_severity} /></div>
          <p className="text-sm text-slate-700">{r.business_impact.summary}</p>
          <p className="mt-2 text-sm text-slate-700"><b className="font-medium">Customers:</b> {r.business_impact.customer_impact}</p>
          <p className="mt-2 text-sm text-slate-700"><b className="font-medium">Exposure:</b> {r.business_impact.regulatory_or_financial_exposure}</p>
        </Card>
        <Card title="Affected services">
          <ul className="space-y-2 text-sm">
            {r.affected_services.map((s) => <li key={s.application_code}><b className="font-medium">{s.application_code}</b> - {s.impact}</li>)}
          </ul>
        </Card>
        <Card title="Escalation">
          <p className={`text-sm font-medium ${r.escalation.recommended ? "text-red-700" : "text-slate-700"}`}>{r.escalation.recommended ? "Escalate now" : "No escalation needed"}</p>
          <p className="mt-1 text-sm text-slate-600">{r.escalation.reason}</p>
        </Card>
        {r.missing_information.length > 0 && <Card title="Missing information"><List items={r.missing_information} /></Card>}
        <Card title={<span className="flex items-center gap-2"><ShieldCheck size={16} aria-hidden="true" /> Guardrails</span>}>
          {r.guardrail_notes.length ? <List items={r.guardrail_notes} /> : <p className="text-sm text-slate-600">No corrections needed - every citation pointed to real evidence.</p>}
        </Card>
      </div>
    </div>
  );
}

function ReviewPanel({ investigation: d, identity, onReviewed }: { investigation: Investigation; identity: Identity; onReviewed: () => void }) {
  const [notes, setNotes] = useState("");
  const [applyHypotheses, setApplyHypotheses] = useState(true);
  const [applyActions, setApplyActions] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (d.status !== "AWAITING_REVIEW") {
    const applied = d.report?.applied;
    return (
      <Card title="Human review">
        <p className="text-sm text-slate-700">
          {d.status === "APPROVED" ? "Approved" : "Rejected"} by <b className="font-medium">{d.reviewed_by}</b> on {formatTime(d.reviewed_at)}.
          {applied && d.status === "APPROVED" && ` ${applied.root_causes} hypotheses and ${applied.actions} actions were added to the incident (still unconfirmed).`}
        </p>
        {d.review_notes && <p className="mt-2 text-sm text-slate-600">Notes: {d.review_notes}</p>}
      </Card>
    );
  }

  const review = async (decision: "APPROVE" | "REJECT") => {
    setBusy(true);
    setError(null);
    try {
      await aiApi.review(d.id, decision, notes.trim(), applyHypotheses, applyActions);
      onReviewed();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Human review - approve or reject this AI analysis" className="ring-2 ring-amber-300">
      {!canAct(identity.role, "INCIDENT_MANAGER") && (
        <p className="mb-3 rounded-md bg-amber-50 p-2 text-sm text-amber-900">
          You are acting as {identity.label}. Only an incident manager can approve; switch user at the top (try it - the API refuses).
        </p>
      )}
      <Field label="Review notes" hint="Say what you checked, e.g. which evidence you verified.">
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={inputClass} />
      </Field>
      <div className="mt-3 flex flex-wrap gap-4 text-sm text-slate-700">
        <label className="flex items-center gap-2"><input type="checkbox" checked={applyHypotheses} onChange={(e) => setApplyHypotheses(e.target.checked)} /> Add hypotheses to the incident</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={applyActions} onChange={(e) => setApplyActions(e.target.checked)} /> Create CAPA actions</label>
      </div>
      <div className="mt-3"><ErrorBanner message={error} onClose={() => setError(null)} /></div>
      <div className="mt-3 flex gap-2">
        <Button variant="success" onClick={() => review("APPROVE")} disabled={busy}><Check size={16} aria-hidden="true" />Approve</Button>
        <Button variant="danger" onClick={() => review("REJECT")} disabled={busy}><X size={16} aria-hidden="true" />Reject</Button>
      </div>
      <p className="mt-2 text-xs text-slate-500">Approving does not confirm a root cause or execute anything - it records the AI's proposals for the team.</p>
    </Card>
  );
}
