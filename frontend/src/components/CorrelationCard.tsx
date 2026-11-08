import { ArrowDownRight, ArrowUpRight, GitCommitHorizontal, Network } from "lucide-react";
import { Link } from "react-router-dom";

import { useApi } from "../hooks/useApi";
import { incidentApi, referenceApi } from "../services/api";
import type { ApplicationRef, Incident, IncidentDetail, Rca } from "../types/incident";
import { SeverityBadge, StatusBadge } from "./Badges";
import { Card } from "./ui";

const WINDOW_HOURS = 3;

type Related = { app: ApplicationRef; direction: "downstream" | "upstream"; critical: boolean; incidents: Incident[] };

/**
 * Change correlation and blast radius: which deployments landed shortly before this incident, and which
 * connected applications have active incidents right now. Read-only - humans decide what is causal.
 */
export default function CorrelationCard({ incident, rca }: { incident: IncidentDetail; rca: Rca | null }) {
  const related = useApi(async (): Promise<Related[]> => {
    const app = await referenceApi.application(incident.application.id);
    const links: Omit<Related, "incidents">[] = [
      ...app.dependents.map((a) => ({ app: a, direction: "downstream" as const, critical: true })),
      ...app.dependencies.map((d) => ({ app: d.depends_on, direction: "upstream" as const, critical: d.is_critical })),
    ];
    const start = new Date(incident.started_at ?? incident.created_at).getTime();
    const window = { created_from: new Date(start - WINDOW_HOURS * 3600e3).toISOString(), created_to: new Date(start + WINDOW_HOURS * 3600e3).toISOString() };
    const seen = new Set<number>();
    const unique = links.filter((l) => !seen.has(l.app.id) && seen.add(l.app.id));
    return Promise.all(
      unique.map(async (l) => ({
        ...l,
        incidents: (await incidentApi.list({ application_id: l.app.id, ...window, page_size: 5, sort: "created_at", order: "asc" })).items,
      })),
    );
  }, [incident.application.id]);

  const changes = rca?.related_changes ?? [];
  const startMs = new Date(incident.started_at ?? incident.created_at).getTime();
  const offset = (iso: string) => {
    const m = Math.round((new Date(iso).getTime() - startMs) / 60000);
    return m === 0 ? "same time" : m > 0 ? `+${m} min` : `${m} min`;
  };
  const impacted = (related.data ?? []).filter((r) => r.incidents.length > 0);
  const quiet = (related.data ?? []).filter((r) => r.incidents.length === 0);

  return (
    <Card title={<span className="flex items-center gap-2"><Network size={16} aria-hidden="true" /> Change correlation &amp; impact</span>}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recent changes linked to this incident</h3>
      {changes.length === 0 ? (
        <p className="mt-1 text-sm text-slate-500">No change linked yet.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {changes.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm ring-1 ring-amber-200">
              <GitCommitHorizontal size={16} className="text-amber-700" aria-hidden="true" />
              <span className="font-mono font-semibold text-amber-900">{c.change.change_reference}</span>
              <span className="text-slate-800">{c.change.title}{c.change.version ? ` (${c.change.version})` : ""}</span>
              {c.minutes_from_deployment_to_incident !== null && (
                <span className="rounded bg-amber-200 px-1.5 py-0.5 text-xs font-semibold text-amber-900">
                  deployed {Math.round(c.minutes_from_deployment_to_incident)} min before impact
                </span>
              )}
              <span className="text-xs text-slate-500">{c.link_status.replaceAll("_", " ").toLowerCase()}</span>
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Connected applications with incidents within {WINDOW_HOURS} h
      </h3>
      {related.loading && !related.data ? (
        <p className="mt-1 text-sm text-slate-500">Checking dependencies…</p>
      ) : impacted.length === 0 ? (
        <p className="mt-1 text-sm text-slate-500">No incidents on connected applications in this window.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {impacted.map((r) => (
            <li key={r.app.id} className="rounded-md px-3 py-2 ring-1 ring-slate-200">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {r.direction === "downstream" ? (
                  <ArrowDownRight size={16} className="text-red-600" aria-hidden="true" />
                ) : (
                  <ArrowUpRight size={16} className="text-sky-600" aria-hidden="true" />
                )}
                <b className="font-semibold text-navy-900">{r.app.code} - {r.app.name}</b>
                <span className="text-xs text-slate-500">
                  {r.direction === "downstream" ? `depends on ${incident.application.code}` : `${incident.application.code} depends on it`}
                  {" · "}{r.app.business_criticality.replace("_", " ").toLowerCase()}
                </span>
              </div>
              <ul className="mt-1.5 space-y-1 pl-6">
                {r.incidents.map((x) => (
                  <li key={x.id} className="flex flex-wrap items-center gap-2 text-sm">
                    <Link to={`/incidents/${x.id}`} className="font-mono text-navy-800 hover:underline">{x.reference_number}</Link>
                    <SeverityBadge severity={x.severity} />
                    <StatusBadge status={x.status} />
                    <span className="text-slate-700">{x.title}</span>
                    <span className="text-xs text-slate-500">{offset(x.created_at)}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {quiet.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">Quiet in this window: {quiet.map((r) => r.app.code).join(", ")}</p>
      )}
      <p className="mt-3 text-xs text-slate-500">Correlation is evidence, not proof - an engineer confirms the cause in Root cause analysis.</p>
    </Card>
  );
}
