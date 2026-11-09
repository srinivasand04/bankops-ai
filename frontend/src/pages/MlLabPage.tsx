import { FlaskConical, Play } from "lucide-react";
import { useState, type ReactNode } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";

import { Button, Card, ErrorBanner, formatTime } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useI18n } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { errorMessage, mlApi } from "../services/api";
import { canAct, type Identity } from "../services/identity";
import type { MlRun, ScoredChange } from "../types/ml";

const TASKS = ["sla_breach", "mttr", "change_risk", "routing", "similar", "clusters", "forecast", "anomaly"] as const;
type Tab = (typeof TASKS)[number] | "changes";

// Two-series charts (train vs test, actual vs forecast) use the first two categorical slots.
const C1 = "#2a78d6";
const C2 = "#eb6834";
const AXIS = { fontSize: 11, fill: "#52514e" };
const GRID = "#e6e4df";
const legendText = (v: string) => <span style={{ color: "#52514e" }}>{v}</span>;

// Metrics shown in each task's comparison table, in order
const METRICS: Record<string, string[]> = {
  sla_breach: ["roc_auc", "pr_auc", "f1", "precision", "recall", "brier"],
  mttr: ["mae_minutes", "rmse_minutes", "r2", "median_abs_error_minutes"],
  change_risk: ["roc_auc", "pr_auc", "f1", "precision", "recall"],
  routing: ["macro_f1", "weighted_f1", "accuracy", "team_accuracy"],
  similar: ["macro_f1", "accuracy", "svd_explained_variance"],
  clusters: ["k", "silhouette", "purity_vs_category"],
  forecast: ["mae_per_week", "applications", "test_weeks"],
  anomaly: ["precision", "recall", "f1", "alerts", "incidents"],
};

export default function MlLabPage({ identity }: { identity: Identity }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("sla_breach");
  const [error, setError] = useState<string | null>(null);
  const tasks = useApi(mlApi.tasks, [], { pollMs: 4000, keepPolling: (d) => !!d?.some((x) => x.status && ["RUNNING", "QUEUED"].includes(x.status.state)) });
  const runs = useApi(() => mlApi.runs(), [tasks.data?.map((x) => x.active?.id).join(",")]);
  const training = tasks.data?.some((x) => x.status && ["RUNNING", "QUEUED"].includes(x.status.state));
  const canTrain = canAct(identity.role, "INCIDENT_MANAGER");

  const trainAll = async () => {
    setError(null);
    try {
      await mlApi.train("all");
      tasks.reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const taskRuns = (task: string) => (runs.data ?? []).filter((r) => r.task === task);
  const trained = (tasks.data ?? []).filter((x) => x.active).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-navy-900"><FlaskConical size={20} aria-hidden="true" /> {t("ml.title")}</h1>
          <p className="text-sm text-slate-600">{t("ml.subtitle")}</p>
          {tasks.data && <p className="mt-1 text-xs text-slate-500">{t("ml.trainedCount", { n: trained, total: tasks.data.length })}</p>}
        </div>
        {canTrain && (
          <Button onClick={trainAll} disabled={training}>
            <Play size={15} aria-hidden="true" /> {training ? t("ml.training") : t("ml.trainAll")}
          </Button>
        )}
      </div>
      <ErrorBanner message={error ?? tasks.error ?? runs.error} onClose={() => setError(null)} />

      <div role="tablist" className="flex flex-wrap gap-1 border-b border-slate-200">
        {[...TASKS, "changes" as const].map((k) => {
          const st = tasks.data?.find((x) => x.task === k)?.status?.state;
          return (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === k ? "border-navy-900 text-navy-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
              {t(`ml.task.${k}` as MessageKey)}{st === "RUNNING" && " …"}
            </button>
          );
        })}
      </div>

      {tab === "changes" ? <ChangeRisk /> : (
        <TaskView task={tab} runs={taskRuns(tab)} status={tasks.data?.find((x) => x.task === tab)?.status ?? null} />
      )}
      <p className="text-xs text-slate-500">{t("ml.honesty")}</p>
    </div>
  );
}

function TaskView({ task, runs, status }: { task: string; runs: MlRun[]; status: { state: string; reason?: string } | null }) {
  const { t } = useI18n();
  const active = runs.find((r) => r.is_active);
  if (!runs.length) {
    return <Card><p className="text-sm text-slate-600">{status?.state === "SKIPPED" ? status.reason : t("ml.notTrained")}</p></Card>;
  }
  const d = active?.details ?? {};
  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-slate-700">{t(`ml.why.${task}` as MessageKey)}</p>
        {active && (
          <p className="mt-2 text-xs text-slate-500">
            {t("ml.split", { train: active.n_train, test: active.n_test, from: formatTime(active.test_from), to: formatTime(active.test_to) })}
          </p>
        )}
      </Card>
      <Comparison task={task} runs={runs} />
      {task === "sla_breach" && active && <ClassifierCharts run={active} />}
      {task === "change_risk" && <ChangeRiskCharts runs={runs} />}
      {task === "mttr" && <MttrCharts runs={runs} />}
      {task === "routing" && active && <RoutingCharts run={active} />}
      {task === "clusters" && active && <ClusterCharts details={d} />}
      {task === "forecast" && active && <ForecastCharts runs={runs} />}
      {task === "anomaly" && <AnomalyCharts runs={runs} />}
      {task === "similar" && <Card><p className="text-sm text-slate-700">{t("ml.similarHint")}</p></Card>}
    </div>
  );
}

function Comparison({ task, runs }: { task: string; runs: MlRun[] }) {
  const { t } = useI18n();
  const cols = METRICS[task] ?? [];
  return (
    <Card title={<span className="text-sm">{t("ml.comparison")}</span>}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">{t("ml.algorithm")}</th>
              {cols.map((c) => <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">{c.replaceAll("_", " ")}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {runs.map((r) => (
              <tr key={r.id} className={r.is_active ? "bg-emerald-50/60" : ""}>
                <td className="whitespace-nowrap px-3 py-2 font-medium text-navy-900">
                  {r.algorithm.replaceAll("_", " ")}
                  {r.is_active && <span className="ml-2 rounded bg-emerald-600 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-white">{t("ml.active")}</span>}
                </td>
                {cols.map((c) => <td key={c} className="whitespace-nowrap px-3 py-2 tabular-nums">{r.metrics[c] ?? "-"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">{t("ml.activeRule")}</p>
    </Card>
  );
}

function ChartCard({ title, children, height = 240 }: { title: string; children: ReactNode; height?: number }) {
  return (
    <Card title={<span className="text-sm">{title}</span>}>
      <div style={{ height }}><ResponsiveContainer width="100%" height="100%">{children as React.ReactElement}</ResponsiveContainer></div>
    </Card>
  );
}

/** Feature effects as horizontal bars. Coefficients can be negative (they lower the prediction): those
 *  bars grow to the left of the centre line. */
function Importance({ items, title }: { items?: { label: string; value: number }[]; title: string }) {
  if (!items?.length) return null;
  const max = Math.max(...items.map((i) => Math.abs(i.value)), 1e-9);
  const signed = items.some((i) => i.value < 0);
  return (
    <Card title={<span className="text-sm">{title}</span>}>
      <ul className="space-y-1.5">
        {items.map((i) => {
          const w = `${(Math.abs(i.value) / max) * (signed ? 50 : 100)}%`;
          return (
            <li key={i.label} className="grid grid-cols-[minmax(0,15rem)_1fr_3.5rem] items-center gap-2 text-xs" title={`${i.label}: ${i.value}`}>
              <span className="truncate text-right text-slate-700">{i.label}</span>
              <span className="relative h-3.5 rounded bg-slate-100">
                {signed && <span className="absolute inset-y-0 left-1/2 w-px bg-slate-400" aria-hidden="true" />}
                <span className="absolute inset-y-0 rounded" style={{
                  width: w, background: i.value < 0 ? C2 : C1,
                  left: signed ? (i.value < 0 ? `calc(50% - ${w})` : "50%") : 0,
                }} />
              </span>
              <span className="text-right tabular-nums text-slate-600">{i.value}</span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function Confusion({ matrix, labels, title }: { matrix: number[][]; labels: string[]; title: string }) {
  const { label } = useI18n();
  const max = Math.max(1, ...matrix.flat());
  return (
    <Card title={<span className="text-sm">{title}</span>}>
      <div className="overflow-x-auto">
        <table className="text-xs">
          <tbody>
            <tr><td />{labels.map((l) => <td key={l} className="px-1 pb-1 text-center text-[10px] text-slate-500">{label(l).slice(0, 12)}</td>)}</tr>
            {matrix.map((row, i) => (
              <tr key={labels[i]}>
                <td className="whitespace-nowrap pr-2 text-right text-[11px] text-slate-600">{label(labels[i])}</td>
                {row.map((v, j) => (
                  <td key={j} className="h-8 w-12 text-center tabular-nums ring-1 ring-white"
                    style={{ background: `rgba(42,120,214,${v / max})`, color: v / max > 0.5 ? "#fff" : "#0b0b0b" }}>{v}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ClassifierCharts({ run }: { run: MlRun }) {
  const { t } = useI18n();
  const d = run.details ?? {};
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Importance items={d.coefficients ?? d.feature_importance} title={t("ml.drivers", { algo: run.algorithm.replaceAll("_", " ") })} />
      <div className="space-y-4">
        {d.confusion_matrix && <Confusion matrix={d.confusion_matrix} labels={[t("ml.no"), t("ml.yes")]} title={t("ml.confusion")} />}
        {d.calibration && (
          <ChartCard title={t("ml.calibration")} height={220}>
            <LineChart data={d.calibration} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
              <CartesianGrid stroke={GRID} />
              <XAxis dataKey="predicted" type="number" domain={[0, 1]} tick={AXIS} />
              <YAxis domain={[0, 1]} tick={AXIS} />
              <Tooltip />
              <Legend formatter={legendText} />
              <Line name={t("ml.observed")} dataKey="observed" stroke={C1} strokeWidth={2} dot={{ r: 3 }} />
              <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#9a9890" strokeDasharray="4 3" />
            </LineChart>
          </ChartCard>
        )}
      </div>
    </div>
  );
}

function ChangeRiskCharts({ runs }: { runs: MlRun[] }) {
  const { t } = useI18n();
  const tree = runs.find((r) => r.algorithm === "decision_tree");
  const active = runs.find((r) => r.is_active);
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        {tree?.details?.bias_variance && (
          <ChartCard title={t("ml.biasVariance")} height={260}>
            <LineChart data={tree.details.bias_variance} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
              <CartesianGrid stroke={GRID} />
              <XAxis dataKey="depth" tick={AXIS} label={{ value: t("ml.depth"), position: "insideBottom", offset: -2, fontSize: 11 }} />
              <YAxis domain={[0.4, 1]} tick={AXIS} />
              <Tooltip />
              <Legend formatter={legendText} />
              <Line name={t("ml.trainScore")} dataKey="train_auc" stroke={C1} strokeWidth={2} dot={{ r: 3 }} />
              <Line name={t("ml.testScore")} dataKey="test_auc" stroke={C2} strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ChartCard>
        )}
        {active && <Importance items={active.details?.feature_importance ?? tree?.details?.feature_importance} title={t("ml.drivers", { algo: (active.details?.feature_importance ? active : tree)?.algorithm.replaceAll("_", " ") ?? "" })} />}
      </div>
      {tree?.details?.rules && (
        <Card title={<span className="text-sm">{t("ml.rules")}</span>}>
          <pre className="max-h-80 overflow-auto rounded bg-slate-50 p-3 text-xs leading-5 text-slate-800">{tree.details.rules}</pre>
        </Card>
      )}
    </div>
  );
}

function MttrCharts({ runs }: { runs: MlRun[] }) {
  const { t } = useI18n();
  const lin = runs.find((r) => r.algorithm === "linear_regression");
  const best = runs.find((r) => r.is_active);
  const rc = lin?.details?.residual_check;
  const sample = (best?.details?.sample ?? []).map((s: { actual: number; predicted: number }) => ({ actual: +(s.actual / 60).toFixed(1), predicted: +(s.predicted / 60).toFixed(1) }));
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard title={t("ml.actualVsPredicted")} height={260}>
        <ScatterChart margin={{ top: 8, right: 12, bottom: 8, left: -8 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis dataKey="actual" type="number" name={t("ml.actualH")} tick={AXIS} scale="log" domain={["auto", "auto"]} />
          <YAxis dataKey="predicted" type="number" name={t("ml.predictedH")} tick={AXIS} scale="log" domain={["auto", "auto"]} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} />
          <Scatter data={sample} fill={C1} fillOpacity={0.6} />
        </ScatterChart>
      </ChartCard>
      {rc && (
        <Card title={<span className="text-sm">{t("ml.residuals")}</span>}>
          <div style={{ height: 170 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rc.histogram} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid vertical={false} stroke={GRID} />
                <XAxis dataKey="x" tick={AXIS} />
                <YAxis tick={AXIS} />
                <Tooltip />
                <Bar dataKey="n" fill={C1} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-slate-600">mean {rc.mean} · std {rc.std} · skew {rc.skew} · corr(|residual|, fitted) {rc.corr_abs_residual_vs_fitted}</p>
          <p className="mt-1 text-xs text-slate-500">{t("ml.residualReading")}</p>
        </Card>
      )}
    </div>
  );
}

function RoutingCharts({ run }: { run: MlRun }) {
  const { t, label } = useI18n();
  const d = run.details ?? {};
  return (
    <div className="space-y-4">
      {d.confusion_matrix && <Confusion matrix={d.confusion_matrix} labels={d.labels} title={t("ml.confusion")} />}
      {d.top_terms && (
        <Card title={<span className="text-sm">{t("ml.topTerms")}</span>}>
          <ul className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(d.top_terms as Record<string, string[]>).map(([cat, terms]) => (
              <li key={cat}><b className="font-medium text-navy-900">{label(cat)}</b><span className="block text-xs text-slate-600">{terms.join(", ")}</span></li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function ClusterCharts({ details }: { details: Record<string, any> }) { // eslint-disable-line @typescript-eslint/no-explicit-any
  const { t, label } = useI18n();
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title={t("ml.elbow")} height={220}>
          <LineChart data={details.elbow} margin={{ top: 8, right: 12, bottom: 0, left: -4 }}>
            <CartesianGrid stroke={GRID} /><XAxis dataKey="k" tick={AXIS} /><YAxis tick={AXIS} /><Tooltip />
            <Line dataKey="inertia" stroke={C1} strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ChartCard>
        <ChartCard title={t("ml.silhouette")} height={220}>
          <LineChart data={details.elbow} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={GRID} /><XAxis dataKey="k" tick={AXIS} /><YAxis tick={AXIS} domain={["auto", "auto"]} /><Tooltip />
            <Line dataKey="silhouette" stroke={C1} strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ChartCard>
      </div>
      <Card title={<span className="text-sm">{t("ml.clusters")}</span>}>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(details.clusters ?? []).map((c: { cluster: number; size: number; top_terms: string[]; main_category: string; category_share: number; main_applications: string[] }) => (
            <li key={c.cluster} className="rounded-md bg-slate-50 p-3 text-sm">
              <div className="flex justify-between"><b className="font-medium text-navy-900">#{c.cluster}</b><span className="text-xs text-slate-500">{c.size}</span></div>
              <p className="mt-1 text-xs text-slate-700">{c.top_terms.join(", ")}</p>
              <p className="mt-1 text-xs text-slate-500">{label(c.main_category)} {Math.round(c.category_share * 100)}% · {c.main_applications.join(", ")}</p>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-slate-500">{t("ml.purityReading")}</p>
      </Card>
    </div>
  );
}

function ForecastCharts({ runs }: { runs: MlRun[] }) {
  const { t } = useI18n();
  const active = runs.find((r) => r.is_active);
  const apps = (active?.details?.per_application ?? []) as { application: string; mae: number; history: { week: string; actual: number }[]; next_weeks: { week: string; forecast: number }[] }[];
  const [app, setApp] = useState(apps[0]?.application);
  const a = apps.find((x) => x.application === app) ?? apps[0];
  if (!a) return null;
  const data = [...a.history.map((h) => ({ week: h.week, actual: h.actual })), ...a.next_weeks.map((n) => ({ week: n.week, forecast: n.forecast }))];
  return (
    <Card title={<span className="text-sm">{t("ml.forecastTitle")}</span>}
      actions={<select value={a.application} onChange={(e) => setApp(e.target.value)} className="rounded-md border border-slate-300 px-2 py-1 text-sm">{apps.map((x) => <option key={x.application}>{x.application}</option>)}</select>}>
      <div style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={GRID} /><XAxis dataKey="week" tick={AXIS} /><YAxis tick={AXIS} allowDecimals={false} /><Tooltip />
            <Legend formatter={legendText} />
            <Line name={t("ml.actual")} dataKey="actual" stroke={C1} strokeWidth={2} dot={{ r: 2 }} />
            <Line name={t("ml.forecast")} dataKey="forecast" stroke={C2} strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-slate-500">{t("ml.forecastMae", { mae: a.mae })}</p>
    </Card>
  );
}

function AnomalyCharts({ runs }: { runs: MlRun[] }) {
  const { t } = useI18n();
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {runs.map((r) => {
        const ex = r.details?.examples?.[0];
        if (!ex) return null;
        const data = ex.points.map((p: { t: string; v: number; flag: boolean }) => ({ t: p.t.slice(5, 16).replace("T", " "), v: p.v, flagged: p.flag ? p.v : null }));
        return (
          <ChartCard key={r.id} title={`${r.algorithm.replaceAll("_", " ")} · ${ex.application} ${ex.metric}`} height={240}>
            <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
              <CartesianGrid stroke={GRID} /><XAxis dataKey="t" tick={AXIS} interval={11} /><YAxis tick={AXIS} /><Tooltip />
              <Legend formatter={legendText} />
              <Line name={t("ml.value")} dataKey="v" stroke={C1} strokeWidth={2} dot={false} />
              <Line name={t("ml.alert")} dataKey="flagged" stroke={C2} strokeWidth={0} dot={{ r: 5, fill: C2 }} />
            </LineChart>
          </ChartCard>
        );
      })}
    </div>
  );
}

function ChangeRisk() {
  const { t, label } = useI18n();
  const changes = useApi(() => mlApi.changes(20));
  const band: Record<string, string> = { LOW: "bg-slate-100 text-slate-700", MEDIUM: "bg-amber-100 text-amber-800", HIGH: "bg-red-100 text-red-800" };
  return (
    <Card title={<span className="text-sm">{t("ml.changesTitle")}</span>}>
      <ErrorBanner message={changes.error} />
      {changes.loading && !changes.data && <p className="text-sm text-slate-500">{t("common.loading")}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>{[t("c.change"), t("c.app"), t("c.title"), t("c.deployed"), t("c.risk"), t("ml.incidentRisk"), t("ml.factors")].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {(changes.data ?? []).map((c: ScoredChange) => (
              <tr key={c.id} className="align-top">
                <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{c.reference}</td>
                <td className="px-3 py-2">{c.application}</td>
                <td className="px-3 py-2">{c.title}</td>
                <td className="whitespace-nowrap px-3 py-2 text-xs">{formatTime(c.deployed_at)}</td>
                <td className="px-3 py-2 text-xs">{label(c.risk_level)}</td>
                <td className="whitespace-nowrap px-3 py-2"><span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${band[c.prediction.band]}`}>{Math.round(c.prediction.incident_probability * 100)}% · {label(c.prediction.band)}</span></td>
                <td className="px-3 py-2 text-xs text-slate-600">{(c.explanation.factors as { code: string; n?: number }[]).map((f) => t(`ml.f.${f.code}` as MessageKey, { n: f.n ?? "" })).join(" · ") || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">{t("ml.changesNote")}</p>
    </Card>
  );
}
