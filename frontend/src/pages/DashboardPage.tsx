import { AlertTriangle, Bot, Clock, Gauge, ShieldAlert, Siren } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { SeverityBadge, SlaBadge, StatusBadge } from "../components/Badges";
import { useApi } from "../hooks/useApi";
import { useI18n } from "../i18n";
import { aiApi, analyticsApi, incidentApi } from "../services/api";

function Kpi({ label, value, icon }: { label: string; value: ReactNode; icon: ReactNode }) {
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex items-center justify-between text-sm text-slate-500">
        {label}
        {icon}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-navy-900">{value}</div>
    </div>
  );
}

// Live KPIs, active incidents and the AI review queue. Charts come with the analytics page.
export default function DashboardPage() {
  const summary = useApi(analyticsApi.summary);
  const active = useApi(() => incidentApi.list({ active_only: true, sort: "severity", order: "asc", page_size: 10 }));
  const reviewQueue = useApi(() => aiApi.list({ status: "AWAITING_REVIEW" }));
  const { t } = useI18n();

  if (summary.error || active.error) {
    return <p className="rounded bg-red-50 p-4 text-red-800">{t("dash.backendDown", { error: summary.error ?? active.error ?? "" })}</p>;
  }
  const s = summary.data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <Kpi label={t("dash.total")} value={s?.total_incidents ?? "-"} icon={<Gauge size={16} />} />
        <Kpi label={t("dash.open")} value={s?.open_incidents ?? "-"} icon={<AlertTriangle size={16} />} />
        <Kpi label={t("dash.openP1")} value={s?.open_p1_incidents ?? "-"} icon={<Siren size={16} />} />
        <Kpi label={t("dash.breaches")} value={s?.sla_breached_incidents ?? "-"} icon={<ShieldAlert size={16} />} />
        <Kpi label={t("dash.mttr")} value={s?.mttr_minutes != null ? `${Math.round(s.mttr_minutes)} min` : "-"} icon={<Clock size={16} />} />
        <Link to="/investigations"><Kpi label={t("dash.awaitingReview")} value={reviewQueue.data?.length ?? "-"} icon={<Bot size={16} />} /></Link>
      </div>

      <section className="rounded-lg bg-white shadow-sm ring-1 ring-slate-200">
        <h2 className="border-b border-slate-200 px-4 py-3 font-semibold text-navy-900">{t("dash.active")}</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                {([t("col.reference"), t("col.severity"), t("col.title"), t("col.application"), t("col.status"), t("col.resolutionSla")]).map((h) => (
                  <th key={h} className="px-4 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {active.data?.items.map((incident) => (
                <tr key={incident.id}>
                  <td className="px-4 py-2 font-mono text-xs"><Link to={`/incidents/${incident.id}`} className="text-navy-800 hover:underline">{incident.reference_number}</Link></td>
                  <td className="px-4 py-2"><SeverityBadge severity={incident.severity} /></td>
                  <td className="px-4 py-2">{incident.title}</td>
                  <td className="px-4 py-2 text-slate-600">{incident.application_name}</td>
                  <td className="px-4 py-2"><StatusBadge status={incident.status} /></td>
                  <td className="px-4 py-2">{incident.sla && <SlaBadge state={incident.sla.resolution.state} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <p className="text-xs text-slate-500">{t("dash.synthetic")}</p>
    </div>
  );
}
