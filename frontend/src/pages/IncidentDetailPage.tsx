import { ArrowLeft, Bot, Check, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { InvestigationBadge, PriorityBadge, SeverityBadge, SlaBadge, SourceBadge, StatusBadge } from "../components/Badges";
import { Button, Card, Empty, ErrorBanner, Field, formatTime, inputClass, minutesLabel, timeAgo } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { aiApi, errorMessage, incidentApi } from "../services/api";
import { canAct, type Identity } from "../services/identity";
import type { CapaAction, IncidentDetail, IncidentStatus, Investigation, RootCause } from "../types/incident";

const NOTE_TYPES = [
  { value: "INVESTIGATION_UPDATE", label: "Investigation update" },
  { value: "EVIDENCE_ADDED", label: "Evidence" },
  { value: "COMMENT", label: "Comment" },
];

export default function IncidentDetailPage({ identity }: { identity: Identity }) {
  const id = Number(useParams().id);
  const incident = useApi(() => incidentApi.get(id), [id]);
  const timeline = useApi(() => incidentApi.timeline(id), [id]);
  const rca = useApi(() => incidentApi.rca(id), [id]);
  const investigations = useApi(() => aiApi.forIncident(id), [id]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    incident.reload();
    timeline.reload();
    rca.reload();
    investigations.reload();
  };

  /** Run an API call, show its error message, refresh everything after. */
  const act = async (call: () => Promise<unknown>) => {
    setError(null);
    try {
      await call();
      refresh();
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    }
  };

  if (incident.error) return <ErrorBanner message={incident.error} />;
  const i = incident.data;
  if (!i) return <p className="text-sm text-slate-500">Loading…</p>;
  const canEdit = canAct(identity.role, "ENGINEER");

  return (
    <div className="space-y-4">
      <Link to="/incidents" className="inline-flex items-center gap-1 text-sm text-slate-600 hover:underline">
        <ArrowLeft size={14} aria-hidden="true" /> Incidents
      </Link>

      <div className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-slate-500">{i.reference_number}</span>
          <SeverityBadge severity={i.severity} />
          <PriorityBadge priority={i.priority} />
          <StatusBadge status={i.status} />
          {i.sla?.is_breached && <span className="text-xs font-semibold text-red-700">SLA breached</span>}
        </div>
        <h1 className="mt-2 text-xl font-semibold text-navy-900">{i.title}</h1>
        <div className="mt-2 grid gap-1 text-sm text-slate-600 sm:grid-cols-2 lg:grid-cols-4">
          <span>Application: <b className="font-medium text-slate-800">{i.application.code} - {i.application_name}</b></span>
          <span>Category: {i.category.replaceAll("_", " ")}</span>
          <span>Assigned: {i.assigned_team ? `${i.assigned_team}${i.assigned_engineer ? ` / ${i.assigned_engineer}` : ""}` : "unassigned"}</span>
          <span>Impact started: {formatTime(i.started_at)}</span>
        </div>
      </div>

      <ErrorBanner message={error} onClose={() => setError(null)} />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Description">
            <p className="whitespace-pre-line text-sm text-slate-700">{i.description}</p>
            {i.business_impact && <p className="mt-3 text-sm"><b className="font-medium">Business impact:</b> {i.business_impact}</p>}
            {i.resolution_summary && <p className="mt-3 text-sm"><b className="font-medium">Resolution:</b> {i.resolution_summary}</p>}
          </Card>

          <RootCauseCard roots={rca.data} identity={identity} act={act} />
          <CapaCard actions={[...(rca.data?.corrective_actions ?? []), ...(rca.data?.preventive_actions ?? [])]} canEdit={canEdit} act={act} />

          <Card title="Timeline">
            {canEdit && <NoteForm onSubmit={(type, text) => act(() => incidentApi.addEvent(id, type, text))} />}
            <ol className="mt-3 space-y-3">
              {[...(timeline.data ?? [])].reverse().map((e) => (
                <li key={e.id} className="border-l-2 border-slate-200 pl-3">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span className="font-medium text-slate-700">{e.event_type.replaceAll("_", " ")}</span>
                    <SourceBadge source={e.source} />
                    <span>{e.created_by}</span>
                    <span>{formatTime(e.created_at)}</span>
                  </div>
                  <p className="mt-0.5 text-sm text-slate-700">{e.description}</p>
                </li>
              ))}
            </ol>
          </Card>
        </div>

        <div className="space-y-4">
          <WorkflowCard incident={i} identity={identity} act={act} />
          <SlaCard incident={i} />
          <AiCard incidentId={id} canEdit={canEdit} investigations={investigations.data ?? []} setError={setError} />
        </div>
      </div>
    </div>
  );
}

type Act = (call: () => Promise<unknown>) => Promise<boolean>;

function WorkflowCard({ incident, identity, act }: { incident: IncidentDetail; identity: Identity; act: Act }) {
  const [team, setTeam] = useState(incident.assigned_team ?? "");
  const [engineer, setEngineer] = useState(incident.assigned_engineer ?? "");
  const [note, setNote] = useState("");
  const [resolution, setResolution] = useState(incident.resolution_summary ?? "");
  const canEdit = canAct(identity.role, "ENGINEER");
  const isManager = canAct(identity.role, "INCIDENT_MANAGER");

  const move = async (status: IncidentStatus) => {
    const extra = { note: note.trim() || undefined, resolution_summary: status === "RESOLVED" ? resolution.trim() || undefined : undefined };
    if (await act(() => incidentApi.changeStatus(incident.id, status, extra))) setNote("");
  };

  if (!canEdit) {
    return <Card title="Workflow"><p className="text-sm text-slate-500">Viewers can read incidents but not change them. Switch user at the top.</p></Card>;
  }

  return (
    <Card title="Workflow">
      {incident.status !== "CLOSED" && (
        <form
          className="mb-4 grid gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            act(() => incidentApi.assign(incident.id, team.trim(), engineer.trim()));
          }}
        >
          <Field label="Assignment">
            <input value={team} onChange={(e) => setTeam(e.target.value)} placeholder="Team" className={inputClass} />
          </Field>
          <input value={engineer} onChange={(e) => setEngineer(e.target.value)} placeholder="Engineer (optional)" className={inputClass} />
          <Button type="submit" variant="secondary" disabled={!team.trim()}>Assign</Button>
        </form>
      )}

      <div className="space-y-2">
        <Field label="Note for the status change" hint={incident.allowed_transitions.includes("REOPENED") ? "Required to reopen" : undefined}>
          <input value={note} onChange={(e) => setNote(e.target.value)} className={inputClass} />
        </Field>
        {incident.allowed_transitions.includes("RESOLVED") && (
          <Field label="Resolution summary" hint="Required to resolve">
            <textarea value={resolution} onChange={(e) => setResolution(e.target.value)} rows={2} className={inputClass} />
          </Field>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          {incident.allowed_transitions.map((status) => {
            const managerOnly = status === "CLOSED" && !isManager;
            return (
              <Button
                key={status}
                variant={status === "RESOLVED" || status === "CLOSED" ? "success" : status === "ESCALATED" ? "danger" : "secondary"}
                onClick={() => move(status)}
                disabled={managerOnly}
                title={managerOnly ? "Only an incident manager can close" : undefined}
              >
                {status.replaceAll("_", " ")}
              </Button>
            );
          })}
        </div>
        <p className="text-xs text-slate-500">Only valid next steps are shown. P1 incidents need a human-confirmed root cause before closing.</p>
      </div>
    </Card>
  );
}

function SlaCard({ incident }: { incident: IncidentDetail }) {
  const sla = incident.sla;
  if (!sla) return null;
  const row = (label: string, clock: typeof sla.response) => (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="text-slate-600">{label} ({clock.target_minutes} min)</span>
      <span className="flex items-center gap-2">
        {clock.actual_minutes === null && <span className="text-xs text-slate-500">{minutesLabel(clock.remaining_minutes)}{clock.remaining_minutes >= 0 ? " left" : ""}</span>}
        <SlaBadge state={clock.state} />
      </span>
    </div>
  );
  return (
    <Card title="SLA">
      {row("Response", sla.response)}
      {row("Resolution", sla.resolution)}
      {sla.escalation_status === "RECOMMENDED" && <p className="mt-2 text-xs font-medium text-amber-700">Escalation recommended</p>}
      <p className="mt-2 text-xs text-slate-500">{sla.note}</p>
    </Card>
  );
}

function AiCard({ incidentId, canEdit, investigations, setError }: { incidentId: number; canEdit: boolean; investigations: Investigation[]; setError: (m: string | null) => void }) {
  const navigate = useNavigate();
  const ai = useApi(aiApi.status);
  const [focus, setFocus] = useState("");
  const [starting, setStarting] = useState(false);

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const inv = await aiApi.analyze(incidentId, focus.trim() || undefined);
      navigate(`/investigations/${inv.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setStarting(false);
    }
  };

  return (
    <Card title={<span className="flex items-center gap-2"><Bot size={16} aria-hidden="true" /> AI analysis</span>}>
      {ai.data && (
        <p className="mb-3 text-xs text-slate-500">
          {ai.data.provider} · {ai.data.model} · {ai.data.ready ? "ready" : <span className="text-red-700">{ai.data.detail}</span>}
        </p>
      )}
      {canEdit && (
        <div className="space-y-2">
          <input value={focus} onChange={(e) => setFocus(e.target.value)} placeholder="Question, e.g. Was the last release the cause?" className={inputClass} />
          <Button onClick={start} disabled={starting || ai.data?.ready === false} className="w-full">
            {starting ? "Starting…" : "Analyse with AI"}
          </Button>
          <p className="text-xs text-slate-500">Runs in the background; results wait for a human review.</p>
        </div>
      )}
      {investigations.length > 0 && (
        <ul className="mt-4 divide-y divide-slate-100 text-sm">
          {investigations.map((inv) => (
            <li key={inv.id} className="flex items-center justify-between py-2">
              <Link to={`/investigations/${inv.id}`} className="text-navy-800 hover:underline">INV-{inv.id}</Link>
              <span className="text-xs text-slate-500">{timeAgo(inv.created_at)}</span>
              <InvestigationBadge status={inv.status} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function RootCauseCard({ roots, identity, act }: { roots: { confirmed_root_causes: RootCause[]; hypotheses: RootCause[] } | null; identity: Identity; act: Act }) {
  const isManager = canAct(identity.role, "INCIDENT_MANAGER");
  const item = (rc: RootCause, reviewable: boolean) => (
    <li key={rc.id} className="rounded-md bg-slate-50 p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <SourceBadge source={rc.source} />
        <span className="font-medium text-slate-700">{rc.status.replaceAll("_", " ")}</span>
        {rc.confidence !== null && <span className="text-slate-500">confidence {Math.round(rc.confidence * 100)}%</span>}
        {rc.confirmed_by && <span className="text-slate-500">confirmed by {rc.confirmed_by}</span>}
      </div>
      <p className="mt-1 text-sm text-slate-800">{rc.description}</p>
      {reviewable && isManager && (
        <div className="mt-2 flex gap-2">
          <Button variant="success" onClick={() => act(() => incidentApi.reviewRootCause(rc.id, "CONFIRM"))}><Check size={14} aria-hidden="true" />Confirm</Button>
          <Button variant="secondary" onClick={() => act(() => incidentApi.reviewRootCause(rc.id, "REJECT"))}><X size={14} aria-hidden="true" />Reject</Button>
        </div>
      )}
    </li>
  );
  return (
    <Card title="Root cause analysis">
      <h3 className="mb-2 text-sm font-medium text-emerald-800">Confirmed root causes</h3>
      {roots?.confirmed_root_causes.length ? <ul className="mb-4 space-y-2">{roots.confirmed_root_causes.map((rc) => item(rc, false))}</ul> : <p className="mb-4 text-sm text-slate-500">None confirmed yet.</p>}
      <h3 className="mb-2 text-sm font-medium text-slate-700">Hypotheses (not confirmed)</h3>
      {roots?.hypotheses.length ? <ul className="space-y-2">{roots.hypotheses.map((rc) => item(rc, true))}</ul> : <p className="text-sm text-slate-500">No hypotheses yet - run an AI analysis or add evidence.</p>}
      {!isManager && roots?.hypotheses.length ? <p className="mt-2 text-xs text-slate-500">Only an incident manager can confirm or reject a root cause.</p> : null}
    </Card>
  );
}

function CapaCard({ actions, canEdit, act }: { actions: CapaAction[]; canEdit: boolean; act: Act }) {
  return (
    <Card title="Corrective and preventive actions (CAPA)">
      {actions.length === 0 ? (
        <Empty>No actions yet.</Empty>
      ) : (
        <ul className="divide-y divide-slate-100">
          {actions.map((a) => (
            <li key={a.id} className="flex flex-wrap items-start justify-between gap-2 py-2 text-sm">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium text-slate-700">{a.action_type}</span>
                  <SourceBadge source={a.source} />
                  <span className="text-slate-500">{a.status.replace("_", " ")}</span>
                  {a.is_overdue && <span className="font-medium text-red-700">overdue</span>}
                  {a.due_date && <span className="text-slate-500">due {a.due_date}</span>}
                </div>
                <p className="mt-0.5 text-slate-800">{a.description}</p>
              </div>
              {canEdit && (a.status === "OPEN" || a.status === "IN_PROGRESS") && (
                <div className="flex gap-1">
                  {a.status === "OPEN" && <Button variant="secondary" onClick={() => act(() => incidentApi.updateAction(a.id, "IN_PROGRESS"))}>Start</Button>}
                  <Button variant="secondary" onClick={() => act(() => incidentApi.updateAction(a.id, "COMPLETED"))}>Complete</Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function NoteForm({ onSubmit }: { onSubmit: (type: string, text: string) => Promise<boolean> }) {
  const [type, setType] = useState(NOTE_TYPES[0].value);
  const [text, setText] = useState("");
  return (
    <form
      className="flex flex-wrap gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (text.trim().length >= 3 && (await onSubmit(type, text.trim()))) setText("");
      }}
    >
      <select aria-label="Note type" value={type} onChange={(e) => setType(e.target.value)} className={`${inputClass} w-auto`}>
        {NOTE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
      </select>
      <input aria-label="Note" value={text} onChange={(e) => setText(e.target.value)} placeholder="Add to the timeline…" className={`${inputClass} min-w-0 flex-1`} />
      <Button type="submit" variant="secondary" disabled={text.trim().length < 3}>Add</Button>
    </form>
  );
}
