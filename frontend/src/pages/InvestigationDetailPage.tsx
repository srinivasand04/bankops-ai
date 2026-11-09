import { AlertTriangle, ArrowLeft, Check, Loader2, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import AgentTeam, { isAgentRun } from "../components/AgentTeam";
import { InvestigationBadge, SeverityBadge } from "../components/Badges";
import { Button, Card, ErrorBanner, Field, formatTime, inputClass } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useI18n } from "../i18n";
import { aiApi, errorMessage } from "../services/api";
import { canAct, type Identity } from "../services/identity";
import type { AnalysisReport, Investigation } from "../types/incident";

export default function InvestigationDetailPage({ identity }: { identity: Identity }) {
  const id = Number(useParams().id);
  // Poll every 5 s while the AI is still working
  const inv = useApi(() => aiApi.get(id), [id], { pollMs: 5000, keepPolling: (d) => !d || d.status === "RUNNING" });
  const { t } = useI18n();

  if (inv.error) return <ErrorBanner message={inv.error} />;
  const d = inv.data;
  if (!d) return <p className="text-sm text-slate-500">{t("common.loading")}</p>;

  return (
    <div className="space-y-4">
      <Link to="/investigations" className="inline-flex items-center gap-1 text-sm text-slate-600 hover:underline">
        <ArrowLeft size={14} aria-hidden="true" /> {t("inv.back")}
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
          {t("inv.requested", { name: d.requested_by, time: formatTime(d.created_at) })}
          {d.model_name && ` · ${d.model_name}`}
          {isAgentRun(d) ? ` · ${t("inv.multiAgent")}` : d.executions[0]?.output_tokens != null && ` · ${t("inv.tokens", { in: d.executions[0].input_tokens ?? 0, out: d.executions[0].output_tokens })}`}
        </p>
      </div>

      {d.status === "RUNNING" && !isAgentRun(d) && <Running startedAt={d.created_at} />}
      {isAgentRun(d) && <AgentTeam inv={d} />}
      {d.status === "FAILED" && <ErrorBanner message={t("inv.failed", { error: d.error_message ?? "" })} />}
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
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3 rounded-lg bg-blue-50 p-4 text-sm text-blue-900 ring-1 ring-blue-200">
      <Loader2 size={20} className="animate-spin" aria-hidden="true" />
      <div>
        <p className="font-medium">{t("inv.running", { t: `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}` })}</p>
        <p className="text-blue-800">{t("inv.runningHint")}</p>
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
  const { t, label } = useI18n();
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Card title={t("rep.summary")}>
          <p className="text-sm leading-relaxed text-slate-800">{r.summary}</p>
          <p className="mt-3 text-xs text-slate-500">{t("rep.confidence", { level: label(r.overall_confidence) })} {r.disclaimer}</p>
        </Card>

        <Card title={t("rep.hypotheses")}>
          <ol className="space-y-3">
            {r.root_cause_hypotheses.map((h, n) => (
              <li key={n} className="rounded-md bg-slate-50 p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-medium text-slate-600">#{n + 1} · {label(h.category)}</span>
                  <span className="text-xs font-semibold text-slate-700">{Math.round(h.confidence * 100)}%</span>
                </div>
                <div className="mt-1 h-1.5 rounded bg-slate-200">
                  <div className="h-1.5 rounded bg-violet-600" style={{ width: `${Math.round(h.confidence * 100)}%` }} />
                </div>
                <p className="mt-2 text-sm text-slate-800">{h.description}</p>
                {h.supporting_evidence_ids.length > 0 && <p className="mt-1 text-xs text-slate-600">{t("rep.supported")}<Ids ids={h.supporting_evidence_ids} /></p>}
                {h.contradicting_evidence_ids.length > 0 && <p className="mt-1 text-xs text-slate-600">{t("rep.contradicted")}<Ids ids={h.contradicting_evidence_ids} /></p>}
                {h.verification_steps.length > 0 && <p className="mt-1 text-xs text-slate-600">{t("rep.verify")} {h.verification_steps.join("; ")}</p>}
              </li>
            ))}
          </ol>
        </Card>

        <Card title={t("rep.facts")}>
          <ul className="space-y-2 text-sm text-slate-700">
            {r.confirmed_facts.map((f, n) => <li key={n}>{f.statement}<Ids ids={f.evidence_ids} /></li>)}
          </ul>
          {r.unverified_statements.length > 0 && (
            <div className="mt-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
              <p className="font-medium">{t("rep.removed")}</p>
              <List items={r.unverified_statements} />
            </div>
          )}
        </Card>

        <Card title={t("rep.actions")}>
          <ul className="divide-y divide-slate-100">
            {r.recommended_actions.map((a, n) => (
              <li key={n} className="py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium text-slate-700">{label(a.action_type)}</span>
                  <span className="text-slate-500">{label(a.urgency)}</span>
                  <span className="text-slate-500">{a.owner_team}</span>
                  {a.requires_human_approval && (
                    <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800">
                      <AlertTriangle size={12} aria-hidden="true" /> {t("rep.needsApproval")}
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
        <Card title={t("rep.impact")}>
          <div className="mb-2 flex items-center gap-2 text-sm">{t("rep.assessed")} <SeverityBadge severity={r.business_impact.assessed_severity} /></div>
          <p className="text-sm text-slate-700">{r.business_impact.summary}</p>
          <p className="mt-2 text-sm text-slate-700"><b className="font-medium">{t("rep.customers")}</b> {r.business_impact.customer_impact}</p>
          <p className="mt-2 text-sm text-slate-700"><b className="font-medium">{t("rep.exposure")}</b> {r.business_impact.regulatory_or_financial_exposure}</p>
        </Card>
        <Card title={t("rep.services")}>
          <ul className="space-y-2 text-sm">
            {r.affected_services.map((s) => <li key={s.application_code}><b className="font-medium">{s.application_code}</b> - {s.impact}</li>)}
          </ul>
        </Card>
        <Card title={t("rep.escalation")}>
          <p className={`text-sm font-medium ${r.escalation.recommended ? "text-red-700" : "text-slate-700"}`}>{r.escalation.recommended ? t("rep.escalateNow") : t("rep.noEscalation")}</p>
          <p className="mt-1 text-sm text-slate-600">{r.escalation.reason}</p>
        </Card>
        {r.missing_information.length > 0 && <Card title={t("rep.missing")}><List items={r.missing_information} /></Card>}
        <Card title={<span className="flex items-center gap-2"><ShieldCheck size={16} aria-hidden="true" /> {t("rep.guardrails")}</span>}>
          {r.guardrail_notes.length ? <List items={r.guardrail_notes} /> : <p className="text-sm text-slate-600">{t("rep.noCorrections")}</p>}
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
  const { t } = useI18n();

  if (d.status !== "AWAITING_REVIEW") {
    const applied = d.report?.applied;
    return (
      <Card title={t("rev.title")}>
        <p className="text-sm text-slate-700">
          {d.status === "APPROVED" ? t("rev.approvedBy") : t("rev.rejectedBy")} <b className="font-medium">{d.reviewed_by}</b> {t("rev.on", { time: formatTime(d.reviewed_at) })}
          {applied && d.status === "APPROVED" && ` ${t("rev.applied", { rc: applied.root_causes, actions: applied.actions })}`}
        </p>
        {d.review_notes && <p className="mt-2 text-sm text-slate-600">{t("rev.notes", { notes: d.review_notes })}</p>}
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
    <Card title={t("rev.panel")} className="ring-2 ring-amber-300">
      {!canAct(identity.role, "INCIDENT_MANAGER") && (
        <p className="mb-3 rounded-md bg-amber-50 p-2 text-sm text-amber-900">
          {t("rev.notManager", { user: t(identity.role === "VIEWER" ? "users.viewer" : identity.role === "ENGINEER" ? "users.engineer" : "users.manager") })}
        </p>
      )}
      <Field label={t("rev.notesLabel")} hint={t("rev.notesHint")}>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={inputClass} />
      </Field>
      <div className="mt-3 flex flex-wrap gap-4 text-sm text-slate-700">
        <label className="flex items-center gap-2"><input type="checkbox" checked={applyHypotheses} onChange={(e) => setApplyHypotheses(e.target.checked)} /> {t("rev.applyHyp")}</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={applyActions} onChange={(e) => setApplyActions(e.target.checked)} /> {t("rev.applyActions")}</label>
      </div>
      <div className="mt-3"><ErrorBanner message={error} onClose={() => setError(null)} /></div>
      <div className="mt-3 flex gap-2">
        <Button variant="success" onClick={() => review("APPROVE")} disabled={busy}><Check size={16} aria-hidden="true" />{t("rev.approve")}</Button>
        <Button variant="danger" onClick={() => review("REJECT")} disabled={busy}><X size={16} aria-hidden="true" />{t("rev.reject")}</Button>
      </div>
      <p className="mt-2 text-xs text-slate-500">{t("rev.footer")}</p>
    </Card>
  );
}
