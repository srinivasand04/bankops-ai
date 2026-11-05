import { Bot } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { InvestigationBadge } from "../components/Badges";
import { Button, Card, Empty, ErrorBanner, Field, inputClass, timeAgo } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { aiApi, errorMessage, incidentApi } from "../services/api";
import { canAct, type Identity } from "../services/identity";
import type { InvestigationStatus } from "../types/incident";

const FILTERS: { value: "" | InvestigationStatus; label: string }[] = [
  { value: "", label: "All" },
  { value: "AWAITING_REVIEW", label: "Awaiting review" },
  { value: "RUNNING", label: "Running" },
  { value: "APPROVED", label: "Approved" },
  { value: "REJECTED", label: "Rejected" },
  { value: "FAILED", label: "Failed" },
];

export default function InvestigationsPage({ identity }: { identity: Identity }) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"" | InvestigationStatus>("");
  const [incidentId, setIncidentId] = useState("");
  const [focus, setFocus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const ai = useApi(aiApi.status);
  const incidents = useApi(() => incidentApi.list({ page_size: 100, sort: "created_at", order: "desc" }));
  // Refresh the list every 10 s while anything is still running
  const list = useApi(() => aiApi.list({ status: filter || undefined, limit: 100 }), [filter], {
    pollMs: 10000,
    keepPolling: (rows) => !!rows?.some((r) => r.status === "RUNNING"),
  });

  const start = async () => {
    if (!incidentId) return setError("Choose an incident first.");
    setStarting(true);
    setError(null);
    try {
      const inv = await aiApi.analyze(Number(incidentId), focus.trim() || undefined);
      navigate(`/investigations/${inv.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setStarting(false);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-navy-900">AI investigation centre</h1>

      {canAct(identity.role, "ENGINEER") && (
        <Card title={<span className="flex items-center gap-2"><Bot size={16} aria-hidden="true" /> Start an analysis</span>}>
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
            <Field label="Incident">
              <select value={incidentId} onChange={(e) => setIncidentId(e.target.value)} className={inputClass}>
                <option value="">Choose an incident…</option>
                {incidents.data?.items.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.reference_number} · {i.application.code} · {i.severity} · {i.title.slice(0, 60)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Question (optional)">
              <input value={focus} onChange={(e) => setFocus(e.target.value)} placeholder="e.g. Was the recent change the cause?" className={inputClass} />
            </Field>
            <Button onClick={start} disabled={starting || ai.data?.ready === false}>{starting ? "Starting…" : "Run analysis"}</Button>
          </div>
          {ai.data && (
            <p className={`mt-3 text-xs ${ai.data.ready ? "text-slate-500" : "text-red-700"}`}>
              Model: {ai.data.provider} / {ai.data.model} ({ai.data.cost}) - {ai.data.detail}
              {ai.data.daily_limit != null && ` · ${ai.data.runs_left_today} of ${ai.data.daily_limit} demo analyses left today`}
            </p>
          )}
          <div className="mt-3"><ErrorBanner message={error} onClose={() => setError(null)} /></div>
        </Card>
      )}

      <Card
        title="Investigations"
        actions={
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.label}
                onClick={() => setFilter(f.value)}
                className={`rounded-full px-3 py-1 text-xs ${filter === f.value ? "bg-navy-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
              >
                {f.label}
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
                {["Investigation", "Incident", "Status", "Question", "Model", "Requested by", "Started"].map((h) => (
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
                  <td className="max-w-xs truncate px-3 py-2 text-slate-600" title={inv.request_text}>{inv.request_text}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500">{inv.model_name ?? "-"}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500">{inv.requested_by}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500">{timeAgo(inv.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.data?.length === 0 && <Empty>No investigations yet.</Empty>}
        </div>
      </Card>
    </div>
  );
}
