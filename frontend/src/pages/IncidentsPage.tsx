import { Plus, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { SeverityBadge, SlaBadge, StatusBadge } from "../components/Badges";
import { Button, Card, Empty, ErrorBanner, Field, inputClass, timeAgo } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { errorMessage, incidentApi, referenceApi, type NewIncident } from "../services/api";
import type { Application, ReferenceData } from "../types/incident";

const ACTIVE = ["OPEN", "ASSIGNED", "INVESTIGATING", "ESCALATED", "ON_HOLD", "REOPENED"];

export default function IncidentsPage() {
  const [appId, setAppId] = useState("");
  const [severity, setSeverity] = useState("");
  const [scope, setScope] = useState<"active" | "all">("active");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);

  const apps = useApi(referenceApi.applications);
  const ref = useApi(referenceApi.referenceData);
  const incidents = useApi(
    () =>
      incidentApi.list({
        page_size: 100,
        application_id: appId || undefined,
        severity: severity || undefined,
        status: scope === "active" ? ACTIVE : undefined,
        search: search.trim().length >= 2 ? search.trim() : undefined,
        sort: "created_at",
        order: "desc",
      }),
    [appId, severity, scope, search],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-navy-900">Incident management</h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? <X size={16} aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />}
          {showForm ? "Close form" : "New incident"}
        </Button>
      </div>

      {showForm && apps.data && ref.data && (
        <CreateIncidentForm applications={apps.data} reference={ref.data} onCancel={() => setShowForm(false)} />
      )}

      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <select aria-label="Application" value={appId} onChange={(e) => setAppId(e.target.value)} className={inputClass}>
            <option value="">All applications</option>
            {apps.data?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} - {a.name}
              </option>
            ))}
          </select>
          <select aria-label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)} className={inputClass}>
            <option value="">All severities</option>
            {["P1", "P2", "P3", "P4"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <select aria-label="Status scope" value={scope} onChange={(e) => setScope(e.target.value as "active" | "all")} className={inputClass}>
            <option value="active">Active incidents</option>
            <option value="all">All incidents</option>
          </select>
          <input aria-label="Search" placeholder="Search title or INC-…" value={search} onChange={(e) => setSearch(e.target.value)} className={inputClass} />
        </div>

        <ErrorBanner message={incidents.error} />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                {["Reference", "Severity", "Title", "Application", "Status", "Assigned", "Resolution SLA", "Created"].map((h) => (
                  <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {incidents.data?.items.map((i) => (
                <tr key={i.id} className="hover:bg-slate-50">
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                    <Link to={`/incidents/${i.id}`} className="text-navy-800 underline-offset-2 hover:underline">
                      {i.reference_number}
                    </Link>
                  </td>
                  <td className="px-3 py-2"><SeverityBadge severity={i.severity} /></td>
                  <td className="px-3 py-2">
                    <Link to={`/incidents/${i.id}`} className="hover:underline">{i.title}</Link>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-600">{i.application.code}</td>
                  <td className="px-3 py-2"><StatusBadge status={i.status} /></td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-600">{i.assigned_engineer ?? i.assigned_team ?? "-"}</td>
                  <td className="px-3 py-2">{i.sla && <SlaBadge state={i.sla.resolution.state} />}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500">{timeAgo(i.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {incidents.data && incidents.data.items.length === 0 && <Empty>No incidents match these filters.</Empty>}
        </div>
      </Card>
    </div>
  );
}

function CreateIncidentForm({ applications, reference, onCancel }: { applications: Application[]; reference: ReferenceData; onCancel: () => void }) {
  const navigate = useNavigate();
  const [form, setForm] = useState<NewIncident>({
    title: "",
    description: "",
    application_id: applications[0]?.id ?? 0,
    severity: "P2",
    category: "APPLICATION",
    business_impact: "",
    assigned_team: "",
    assigned_engineer: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (key: keyof NewIncident, value: string | number) => setForm((f) => ({ ...f, [key]: value }));
  const selectedSeverity = reference.severities.find((s) => s.code === form.severity);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.title.trim().length < 5) return setError("Title needs at least 5 characters.");
    if (form.description.trim().length < 10) return setError("Description needs at least 10 characters.");
    setSaving(true);
    setError(null);
    try {
      const created = await incidentApi.create({
        ...form,
        title: form.title.trim(),
        description: form.description.trim(),
        business_impact: form.business_impact?.trim() || undefined,
        assigned_team: form.assigned_team?.trim() || undefined,
        assigned_engineer: form.assigned_engineer?.trim() || undefined,
      });
      navigate(`/incidents/${created.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setSaving(false);
    }
  };

  return (
    <Card title="New incident">
      <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
        <Field label="Application">
          <select value={form.application_id} onChange={(e) => set("application_id", Number(e.target.value))} className={inputClass}>
            {applications.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} - {a.name} ({a.business_criticality.replace("_", " ")})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Severity" hint={selectedSeverity ? `${selectedSeverity.label}: ${selectedSeverity.criteria[0]}. Demo SLA ${selectedSeverity.response_target_minutes} min response / ${selectedSeverity.resolution_target_minutes} min resolution.` : undefined}>
          <select value={form.severity} onChange={(e) => set("severity", e.target.value)} className={inputClass}>
            {reference.severities.map((s) => (
              <option key={s.code} value={s.code}>
                {s.code} - {s.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Title">
          <input value={form.title} onChange={(e) => set("title", e.target.value)} className={inputClass} placeholder="e.g. Core banking balance enquiries timing out" />
        </Field>
        <Field label="Category">
          <select value={form.category} onChange={(e) => set("category", e.target.value)} className={inputClass}>
            {reference.categories.map((c) => (
              <option key={c} value={c}>
                {c.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </Field>
        <div className="md:col-span-2">
          <Field label="Description">
            <textarea value={form.description} onChange={(e) => set("description", e.target.value)} rows={3} className={inputClass} placeholder="What is failing, since when, and what users see" />
          </Field>
        </div>
        <Field label="Business impact (optional)">
          <input value={form.business_impact} onChange={(e) => set("business_impact", e.target.value)} className={inputClass} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Assign to team (optional)" hint="Assigning acknowledges the incident">
            <input value={form.assigned_team} onChange={(e) => set("assigned_team", e.target.value)} className={inputClass} />
          </Field>
          <Field label="Engineer (optional)">
            <input value={form.assigned_engineer} onChange={(e) => set("assigned_engineer", e.target.value)} className={inputClass} />
          </Field>
        </div>
        <div className="space-y-3 md:col-span-2">
          <ErrorBanner message={error} onClose={() => setError(null)} />
          <div className="flex gap-2">
            <Button type="submit" disabled={saving}>{saving ? "Creating…" : "Create incident"}</Button>
            <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
          </div>
          <p className="text-xs text-slate-500">Priority is derived from severity and the application's criticality. The incident gets the next INC- number.</p>
        </div>
      </form>
    </Card>
  );
}
