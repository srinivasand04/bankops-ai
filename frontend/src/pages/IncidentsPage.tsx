import { Plus, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { SeverityBadge, SlaBadge, StatusBadge } from "../components/Badges";
import { Button, Card, Empty, ErrorBanner, Field, inputClass, timeAgo } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useI18n } from "../i18n";
import { errorMessage, incidentApi, referenceApi, type NewIncident } from "../services/api";
import type { Application, ReferenceData } from "../types/incident";

const ACTIVE = ["OPEN", "ASSIGNED", "INVESTIGATING", "ESCALATED", "ON_HOLD", "REOPENED"];

export default function IncidentsPage() {
  const [appId, setAppId] = useState("");
  const [severity, setSeverity] = useState("");
  const [scope, setScope] = useState<"active" | "all">("active");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const { t } = useI18n();

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
        <h1 className="text-xl font-semibold text-navy-900">{t("inc.title")}</h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? <X size={16} aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />}
          {showForm ? t("inc.closeForm") : t("inc.new")}
        </Button>
      </div>

      {showForm && apps.data && ref.data && (
        <CreateIncidentForm applications={apps.data} reference={ref.data} onCancel={() => setShowForm(false)} />
      )}

      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <select aria-label={t("col.application")} value={appId} onChange={(e) => setAppId(e.target.value)} className={inputClass}>
            <option value="">{t("inc.allApps")}</option>
            {apps.data?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} - {a.name}
              </option>
            ))}
          </select>
          <select aria-label={t("col.severity")} value={severity} onChange={(e) => setSeverity(e.target.value)} className={inputClass}>
            <option value="">{t("inc.allSeverities")}</option>
            {["P1", "P2", "P3", "P4"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <select aria-label={t("col.status")} value={scope} onChange={(e) => setScope(e.target.value as "active" | "all")} className={inputClass}>
            <option value="active">{t("inc.active")}</option>
            <option value="all">{t("inc.all")}</option>
          </select>
          <input aria-label={t("inc.search")} placeholder={t("inc.search")} value={search} onChange={(e) => setSearch(e.target.value)} className={inputClass} />
        </div>

        <ErrorBanner message={incidents.error} />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                {[t("col.reference"), t("col.severity"), t("col.title"), t("col.application"), t("col.status"), t("col.assigned"), t("col.resolutionSla"), t("col.created")].map((h) => (
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
          {incidents.data && incidents.data.items.length === 0 && <Empty>{t("inc.noMatch")}</Empty>}
        </div>
      </Card>
    </div>
  );
}

function CreateIncidentForm({ applications, reference, onCancel }: { applications: Application[]; reference: ReferenceData; onCancel: () => void }) {
  const navigate = useNavigate();
  const { t, label } = useI18n();
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
    if (form.title.trim().length < 5) return setError(t("form.titleShort"));
    if (form.description.trim().length < 10) return setError(t("form.descriptionShort"));
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
    <Card title={t("inc.new")}>
      <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
        <Field label={t("form.application")}>
          <select value={form.application_id} onChange={(e) => set("application_id", Number(e.target.value))} className={inputClass}>
            {applications.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} - {a.name} ({label(a.business_criticality)})
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("form.severity")} hint={selectedSeverity ? t("form.severityHint", { label: selectedSeverity.label, criteria: selectedSeverity.criteria[0], response: selectedSeverity.response_target_minutes, resolution: selectedSeverity.resolution_target_minutes }) : undefined}>
          <select value={form.severity} onChange={(e) => set("severity", e.target.value)} className={inputClass}>
            {reference.severities.map((s) => (
              <option key={s.code} value={s.code}>
                {s.code} - {s.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("form.title")}>
          <input value={form.title} onChange={(e) => set("title", e.target.value)} className={inputClass} placeholder={t("form.titlePh")} />
        </Field>
        <Field label={t("form.category")}>
          <select value={form.category} onChange={(e) => set("category", e.target.value)} className={inputClass}>
            {reference.categories.map((c) => (
              <option key={c} value={c}>
                {label(c)}
              </option>
            ))}
          </select>
        </Field>
        <div className="md:col-span-2">
          <Field label={t("form.description")}>
            <textarea value={form.description} onChange={(e) => set("description", e.target.value)} rows={3} className={inputClass} placeholder={t("form.descriptionPh")} />
          </Field>
        </div>
        <Field label={t("form.impact")}>
          <input value={form.business_impact} onChange={(e) => set("business_impact", e.target.value)} className={inputClass} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("form.team")} hint={t("form.teamHint")}>
            <input value={form.assigned_team} onChange={(e) => set("assigned_team", e.target.value)} className={inputClass} />
          </Field>
          <Field label={t("form.engineer")}>
            <input value={form.assigned_engineer} onChange={(e) => set("assigned_engineer", e.target.value)} className={inputClass} />
          </Field>
        </div>
        <div className="space-y-3 md:col-span-2">
          <ErrorBanner message={error} onClose={() => setError(null)} />
          <div className="flex gap-2">
            <Button type="submit" disabled={saving}>{saving ? t("form.creating") : t("form.create")}</Button>
            <Button type="button" variant="secondary" onClick={onCancel}>{t("common.cancel")}</Button>
          </div>
          <p className="text-xs text-slate-500">{t("form.priorityNote")}</p>
        </div>
      </form>
    </Card>
  );
}
