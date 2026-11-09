import { Brain, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../hooks/useApi";
import { useI18n } from "../i18n";
import { mlApi } from "../services/api";
import type { MlPrediction } from "../types/ml";
import { SeverityBadge } from "./Badges";
import { Card } from "./ui";

const BAND = { LOW: "bg-slate-100 text-slate-700", MEDIUM: "bg-amber-100 text-amber-800", HIGH: "bg-red-100 text-red-800" } as Record<string, string>;

/** Model suggestions for one incident. They never change the incident: a person decides. */
export default function MlInsightsCard({ incidentId }: { incidentId: number }) {
  const { t, label } = useI18n();
  const [refresh, setRefresh] = useState(0);
  const preds = useApi(() => mlApi.incidentPredictions(incidentId, refresh > 0), [incidentId, refresh]);
  const by = Object.fromEntries((preds.data ?? []).map((p) => [p.task, p])) as Record<string, MlPrediction>;
  const sla = by.sla_breach?.prediction;
  const mttr = by.mttr?.prediction;
  const routing = by.routing?.prediction;
  const cluster = by.clusters?.prediction;
  const similar = (by.similar?.prediction.similar ?? []) as { id: number; reference: string; title: string; severity: "P1" | "P2" | "P3" | "P4"; application: string; similarity: number }[];

  return (
    <Card
      title={<span className="flex items-center gap-2"><Brain size={16} aria-hidden="true" /> {t("ml.insights")}</span>}
      actions={
        <button onClick={() => setRefresh((n) => n + 1)} className="inline-flex items-center gap-1 text-xs text-navy-800 hover:underline">
          <RefreshCw size={12} aria-hidden="true" /> {t("ml.recompute")}
        </button>
      }
    >
      {preds.loading && !preds.data && <p className="text-sm text-slate-500">{t("common.loading")}</p>}
      {preds.data && preds.data.length === 0 && <p className="text-sm text-slate-500">{t("ml.noModels")}</p>}
      {preds.data && preds.data.length > 0 && (
        <div className="space-y-3 text-sm">
          {sla && (
            <Row label={t("ml.breachRisk")} evidence={by.sla_breach.evidence_id}>
              <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${BAND[sla.band]}`}>{Math.round(sla.breach_probability * 100)}% · {label(sla.band)}</span>
            </Row>
          )}
          {mttr && (
            <Row label={t("ml.predictedMttr")} evidence={by.mttr.evidence_id}>
              <b className="font-semibold text-navy-900">{t("rpt.hours", { n: mttr.predicted_hours })}</b>
              {by.mttr.explanation.typical_error_minutes && <span className="ml-1 text-xs text-slate-500">± {Math.round(by.mttr.explanation.typical_error_minutes / 60)} h</span>}
            </Row>
          )}
          {routing && (
            <Row label={t("ml.suggested")} evidence={by.routing.evidence_id}>
              <span>{label(routing.suggested_category)} ({Math.round(routing.confidence * 100)}%)</span>
              {routing.suggested_team && <span className="block text-xs text-slate-600">{t("ml.team")}: {routing.suggested_team} ({Math.round(routing.team_confidence * 100)}%)</span>}
              <span className={`block text-xs ${routing.matches_recorded ? "text-emerald-700" : "text-amber-700"}`}>
                {routing.matches_recorded ? t("ml.matches") : t("ml.differs")}
              </span>
            </Row>
          )}
          {cluster && (
            <Row label={t("ml.pattern")} evidence={by.clusters.evidence_id}>
              <span className="text-xs text-slate-700">#{cluster.cluster} · {cluster.top_terms.slice(0, 4).join(", ")} ({cluster.cluster_size})</span>
            </Row>
          )}
          {similar.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{t("ml.similar")}</p>
              <ul className="mt-1 space-y-1">
                {similar.map((s) => (
                  <li key={s.id} className="flex items-center gap-2">
                    <Link to={`/incidents/${s.id}`} className="font-mono text-xs text-navy-800 hover:underline">{s.reference}</Link>
                    <SeverityBadge severity={s.severity} />
                    <span className="min-w-0 flex-1 truncate text-xs text-slate-700" title={s.title}>{s.title}</span>
                    <span className="text-xs tabular-nums text-slate-500">{Math.round(s.similarity * 100)}%</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-slate-500">{t("ml.disclaimer")}</p>
        </div>
      )}
    </Card>
  );
}

function Row({ label, evidence, children }: { label: string; evidence: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-slate-600">{label} <code className="text-[10px] text-slate-400">{evidence}</code></span>
      <span className="text-right">{children}</span>
    </div>
  );
}
