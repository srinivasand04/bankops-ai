import { Bot } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ModePicker, type AnalysisMode } from "../components/AgentTeam";
import { InvestigationBadge } from "../components/Badges";
import { Button, Card, Empty, ErrorBanner, Field, inputClass, timeAgo } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useI18n } from "../i18n";
import { aiApi, errorMessage, incidentApi } from "../services/api";
import { canAct, type Identity } from "../services/identity";
import type { InvestigationStatus } from "../types/incident";

const FILTERS: ("" | InvestigationStatus)[] = ["", "AWAITING_REVIEW", "RUNNING", "APPROVED", "REJECTED", "FAILED"];

export default function InvestigationsPage({ identity }: { identity: Identity }) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"" | InvestigationStatus>("");
  const [incidentId, setIncidentId] = useState("");
  const [focus, setFocus] = useState("");
  const [mode, setMode] = useState<AnalysisMode>("agents");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const { t, label } = useI18n();

  const ai = useApi(aiApi.status);
  const incidents = useApi(() => incidentApi.list({ page_size: 100, sort: "created_at", order: "desc" }));
  // Refresh the list every 10 s while anything is still running
  const list = useApi(() => aiApi.list({ status: filter || undefined, limit: 100 }), [filter], {
    pollMs: 10000,
    keepPolling: (rows) => !!rows?.some((r) => r.status === "RUNNING"),
  });

  const start = async () => {
    if (!incidentId) return setError(t("invs.chooseFirst"));
    setStarting(true);
    setError(null);
    try {
      const run = mode === "agents" ? aiApi.investigate : aiApi.analyze;
      const inv = await run(Number(incidentId), focus.trim() || undefined);
      navigate(`/investigations/${inv.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setStarting(false);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-navy-900">{t("invs.title")}</h1>

      {canAct(identity.role, "ENGINEER") && (
        <Card title={<span className="flex items-center gap-2"><Bot size={16} aria-hidden="true" /> {t("invs.start")}</span>}>
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
            <Field label={t("invs.incident")}>
              <select value={incidentId} onChange={(e) => setIncidentId(e.target.value)} className={inputClass}>
                <option value="">{t("invs.choose")}</option>
                {incidents.data?.items.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.reference_number} · {i.application.code} · {i.severity} · {i.title.slice(0, 60)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("invs.question")}>
              <input value={focus} onChange={(e) => setFocus(e.target.value)} placeholder={t("invs.questionPh")} className={inputClass} />
            </Field>
            <Button onClick={start} disabled={starting || ai.data?.ready === false}>{starting ? t("ai.starting") : mode === "agents" ? t("ai.runTeam") : t("invs.run")}</Button>
          </div>
          <div className="mt-3"><ModePicker mode={mode} onChange={setMode} agentsLeft={ai.data?.agent_runs_left_today} /></div>
          {ai.data && (
            <p className={`mt-3 text-xs ${ai.data.ready ? "text-slate-500" : "text-red-700"}`}>
              {t("invs.modelLine", { provider: ai.data.provider, model: ai.data.model, cost: ai.data.cost, detail: ai.data.detail })}
              {ai.data.daily_limit != null && ` · ${t("invs.left", { n: ai.data.runs_left_today ?? 0, limit: ai.data.daily_limit })}`}
            </p>
          )}
          <div className="mt-3"><ErrorBanner message={error} onClose={() => setError(null)} /></div>
        </Card>
      )}

      <Card
        title={t("invs.list")}
        actions={
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <button
                key={f || "all"}
                onClick={() => setFilter(f)}
                className={`rounded-full px-3 py-1 text-xs ${filter === f ? "bg-navy-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
              >
                {f ? label(f) : t("filter.all")}
              </button>
            ))}
          </div>
        }
      >
        <ErrorBanner message={list.error} />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                {[t("col.investigation"), t("col.incident"), t("col.status"), t("col.type"), t("col.question"), t("col.model"), t("col.requestedBy"), t("col.started")].map((h) => (
                  <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {list.data?.map((inv) => (
                <tr key={inv.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs">
                    <Link to={`/investigations/${inv.id}`} className="text-navy-800 hover:underline">INV-{inv.id}</Link>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    {inv.incident_id ? <Link to={`/incidents/${inv.incident_id}`} className="hover:underline">{inv.incident_reference}</Link> : "-"}
                  </td>
                  <td className="px-3 py-2"><InvestigationBadge status={inv.status} /></td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600">{inv.agents_selected.includes("supervisor") ? t("invs.team", { n: inv.agents_selected.length }) : t("invs.single")}</td>
                  <td className="max-w-xs truncate px-3 py-2 text-slate-600" title={inv.request_text}>{inv.request_text}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500">{inv.model_name ?? "-"}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500">{inv.requested_by}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500">{timeAgo(inv.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.data?.length === 0 && <Empty>{t("invs.none")}</Empty>}
        </div>
      </Card>
    </div>
  );
}
