import { Download, FileText, Printer } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { SeverityBadge, StatusBadge } from "../components/Badges";
import { Card, Empty, ErrorBanner, formatTime, inputClass } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useI18n } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { reportsApi } from "../services/api";
import type { Severity } from "../types/incident";
import type { ManagementPack } from "../types/reports";

const PERIODS = [30, 90, 180, 365];
const TABS = ["pack", "scorecard", "sla", "trends", "change", "problems"] as const;
type Tab = (typeof TABS)[number];

// Chart colours. Severity is ordered, so one hue light -> dark (P1 darkest); single-series bars use one blue.
const SEVERITY_COLORS: Record<Severity, string> = { P1: "#9f1d14", P2: "#d6452f", P3: "#ef8a6d", P4: "#f6c3b2" };
const BAR = "#2a78d6";
const AXIS = { fontSize: 11, fill: "#52514e" };
const GRID = "#e6e4df";

const RAG_STYLE: Record<string, string> = {
  RED: "bg-red-100 text-red-800 ring-red-300",
  AMBER: "bg-amber-100 text-amber-900 ring-amber-300",
  GREEN: "bg-emerald-100 text-emerald-800 ring-emerald-300",
};
const RAG_DOT: Record<string, string> = { RED: "bg-red-600", AMBER: "bg-amber-500", GREEN: "bg-emerald-600" };

const hours = (m: number | null | undefined) => (m == null ? "-" : `${(m / 60).toFixed(1)} h`);
const pct = (v: number | null | undefined) => (v == null ? "-" : `${v}%`);

/** Download rows as CSV (UTF-8 with BOM so Excel opens accents correctly). */
function downloadCsv(name: string, input: object[]) {
  const rows = input as Record<string, unknown>[];
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const esc = (v: unknown) => {
    const s = v == null ? "" : Array.isArray(v) ? v.join(" ") : String(v);
    return /[",\n;]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
  };
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `${name}.csv` });
  a.click();
  URL.revokeObjectURL(url);
}

export default function ReportsPage() {
  const { t } = useI18n();
  const [days, setDays] = useState(90);
  const [tab, setTab] = useState<Tab>("pack");
  const pack = useApi(() => reportsApi.managementPack(days), [days]);
  const p = pack.data;

  const csvFor: Record<Exclude<Tab, "pack">, () => void> = {
    scorecard: () => p && downloadCsv(`scorecard-${days}d`, p.scorecard.applications),
    sla: () => p && downloadCsv(`sla-breaching-${days}d`, p.sla.breaching_now.length ? p.sla.breaching_now : p.sla.by_application),
    trends: () => p && downloadCsv(`trends-${days}d`, p.trends.points),
    change: () => p && downloadCsv(`change-risk-${days}d`, p.change_risk.by_application),
    problems: () => p && downloadCsv(`problems-${days}d`, p.problems.recurring),
  };
  const sections: Record<Exclude<Tab, "pack">, ReactNode> = p ? {
    scorecard: <Scorecard p={p} />,
    sla: <SlaReport p={p} />,
    trends: <Trends p={p} />,
    change: <ChangeRisk p={p} />,
    problems: <Problems p={p} />,
  } : ({} as Record<Exclude<Tab, "pack">, ReactNode>);

  return (
    <div className="report-root space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-navy-900">{t("rpt.title")}</h1>
          <p className="text-sm text-slate-600">{t("rpt.subtitle")}</p>
          {p && (
            <p className="mt-1 text-xs text-slate-500">
              {t("rpt.generated", { time: formatTime(p.period.generated_at), from: formatTime(p.period.from), to: formatTime(p.period.to) })}
            </p>
          )}
        </div>
        <div className="no-print flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            {t("rpt.period")}
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} className={`${inputClass} w-auto`}>
              {PERIODS.map((d) => <option key={d} value={d}>{t("rpt.days", { n: d })}</option>)}
            </select>
          </label>
          {tab !== "pack" && (
            <button onClick={csvFor[tab]} disabled={!p} className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-2 text-sm font-medium text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50">
              <Download size={15} aria-hidden="true" /> {t("rpt.csv")}
            </button>
          )}
          <button onClick={() => window.print()} disabled={!p} className="inline-flex items-center gap-1.5 rounded-md bg-navy-900 px-3 py-2 text-sm font-medium text-white hover:bg-navy-800 disabled:opacity-50">
            <Printer size={15} aria-hidden="true" /> {t("rpt.print")}
          </button>
        </div>
      </div>

      <div role="tablist" className="no-print flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${tab === k ? "border-navy-900 text-navy-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}
          >
            {k === "pack" && <FileText size={15} aria-hidden="true" />}
            {k === "pack" ? t("rpt.pack") : t(`rpt.tab.${k}` as MessageKey)}
          </button>
        ))}
      </div>

      <ErrorBanner message={pack.error} />
      {!p && !pack.error && <p className="text-sm text-slate-500">{t("rpt.loading")}</p>}

      {p && tab === "pack" && (
        <div className="space-y-8">
          <p className="no-print rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-900 ring-1 ring-sky-200">{t("rpt.packHint")}</p>
          {(Object.keys(sections) as Exclude<Tab, "pack">[]).map((k, n) => (
            <section key={k} className={n > 0 ? "print-break" : ""}>
              <h2 className="mb-1 text-lg font-semibold text-navy-900">{n + 1}. {t(`rpt.tab.${k}` as MessageKey)}</h2>
              <p className="mb-3 text-sm text-slate-600">{t(`rpt.desc.${k}` as MessageKey)}</p>
              {sections[k]}
            </section>
          ))}
        </div>
      )}
      {p && tab !== "pack" && (
        <section>
          <p className="mb-3 text-sm text-slate-600">{t(`rpt.desc.${tab}` as MessageKey)}</p>
          {sections[tab]}
        </section>
      )}
      <p className="text-xs text-slate-500">{t("rpt.slaNote")}</p>
    </div>
  );
}

// ---- building blocks ----------------------------------------------------------------------

function Kpis({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-lg bg-white p-3 shadow-sm ring-1 ring-slate-200">
          <div className="text-xs text-slate-500">{label}</div>
          <div className="mt-1 text-xl font-semibold tabular-nums text-navy-900">{value}</div>
        </div>
      ))}
    </div>
  );
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase text-slate-500">
          <tr>{head.map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}

const td = "whitespace-nowrap px-3 py-1.5 tabular-nums";

function Rag({ value }: { value: string }) {
  const { t } = useI18n();
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${RAG_STYLE[value]}`}>
      <span className={`h-2 w-2 rounded-full ${RAG_DOT[value]}`} aria-hidden="true" />
      {t(`rag.${value}` as MessageKey)}
    </span>
  );
}

function ChartCard({ title, children, height = 260 }: { title: string; children: ReactNode; height?: number }) {
  return (
    <Card title={<span className="text-sm">{title}</span>}>
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">{children as React.ReactElement}</ResponsiveContainer>
      </div>
    </Card>
  );
}

// ---- 1. scorecard ------------------------------------------------------------------------

function Scorecard({ p }: { p: ManagementPack }) {
  const { t, label } = useI18n();
  const s = p.scorecard;
  const tot = s.totals;
  const chart = [...s.applications].sort((a, b) => b.incidents - a.incidents);
  return (
    <div className="space-y-4">
      <Kpis items={[
        [t("kpi.applications"), tot.applications],
        [t("kpi.incidents"), tot.incidents.toLocaleString()],
        [t("kpi.open"), tot.open],
        [t("kpi.sla"), pct(tot.sla_compliance_pct)],
        [t("kpi.breaching"), tot.breaching_now],
        [t("kpi.mttr"), hours(tot.mttr_minutes)],
      ]} />
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
        {(["RED", "AMBER", "GREEN"] as const).map((r) => (
          <span key={r} className="inline-flex items-center gap-1.5"><Rag value={r} /> {tot.rag[r] ?? 0}</span>
        ))}
        <span className="text-xs text-slate-500">{t("rag.rules")}: {t("rpt.ragRules")}</span>
      </div>
      <Card>
        <Table head={[t("c.app"), t("c.tier"), t("c.rag"), t("c.incidents"), t("c.open"), t("c.p1"), t("c.sla"), t("c.breaching"), t("c.mttr"), t("c.mtta"), t("c.changes"), t("c.failed"), t("c.topCategory")]}>
          {s.applications.map((a) => (
            <tr key={a.code} className="hover:bg-slate-50">
              <td className="px-3 py-1.5"><b className="font-medium text-navy-900">{a.code}</b> <span className="text-slate-500">{a.name}</span></td>
              <td className={td}>{label(a.tier)}</td>
              <td className={td}><Rag value={a.rag} /></td>
              <td className={td}>{a.incidents}</td>
              <td className={td}>{a.open}</td>
              <td className={td}>{a.p1}{a.open_p1 > 0 && <span className="ml-1 text-xs font-semibold text-red-700">({a.open_p1})</span>}</td>
              <td className={td}>{pct(a.sla_compliance_pct)}</td>
              <td className={`${td} ${a.breaching_now ? "font-semibold text-red-700" : ""}`}>{a.breaching_now}</td>
              <td className={td}>{hours(a.mttr_minutes)}</td>
              <td className={td}>{hours(a.mtta_minutes)}</td>
              <td className={td}>{a.changes}</td>
              <td className={td}>{a.failed_changes}</td>
              <td className={td}>{a.top_category ? label(a.top_category) : "-"}</td>
            </tr>
          ))}
        </Table>
      </Card>
      <ChartCard title={t("ch.incidentsByApp")} height={300}>
        <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="code" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip cursor={{ fill: "rgba(19,34,74,0.06)" }} formatter={(v) => [v, t("c.incidents")]} labelFormatter={(code) => chart.find((a) => a.code === code)?.name ?? code} />
          <Bar dataKey="incidents" fill={BAR} radius={[4, 4, 0, 0]} maxBarSize={36} />
        </BarChart>
      </ChartCard>
    </div>
  );
}

// ---- 2. SLA performance ------------------------------------------------------------------

function SlaReport({ p }: { p: ManagementPack }) {
  const { t, label } = useI18n();
  const s = p.sla;
  const chart = s.by_application.filter((a) => a.compliance_pct != null);
  return (
    <div className="space-y-4">
      <Kpis items={[
        [t("c.response"), pct(s.overall.response.compliance_pct)],
        [t("c.resolution"), pct(s.overall.resolution.compliance_pct)],
        [t("c.met"), s.overall.resolution.met],
        [t("c.breached"), s.overall.resolution.breached],
        [t("c.pending"), s.overall.resolution.pending],
        [t("kpi.breaching"), s.breaching_now_total],
      ]} />
      <div className="grid gap-4 2xl:grid-cols-2">
        <Card title={<span className="text-sm">{t("rpt.bySeverity")}</span>}>
          <Table head={[t("c.severity"), t("c.incidents"), t("c.target"), t("c.response"), t("c.resolution"), t("c.breached")]}>
            {s.by_severity.map((r) => (
              <tr key={r.severity}>
                <td className={td}><SeverityBadge severity={r.severity} /></td>
                <td className={td}>{r.incidents}</td>
                <td className={td}>{r.response_target_minutes} / {r.resolution_target_minutes} min</td>
                <td className={td}>{pct(r.response.compliance_pct)}</td>
                <td className={td}>{pct(r.resolution.compliance_pct)}</td>
                <td className={td}>{r.resolution.breached}</td>
              </tr>
            ))}
          </Table>
        </Card>
        <ChartCard title={t("ch.slaByApp")} height={250}>
          <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="code" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
            <YAxis domain={[0, 100]} tick={AXIS} tickLine={false} axisLine={false} unit="%" />
            <Tooltip cursor={{ fill: "rgba(19,34,74,0.06)" }} formatter={(v) => [`${v}%`, t("c.sla")]} labelFormatter={(code) => chart.find((a) => a.code === code)?.name ?? code} />
            <ReferenceLine y={95} stroke="#52514e" strokeDasharray="4 3" />
            <Bar dataKey="compliance_pct" radius={[4, 4, 0, 0]} maxBarSize={36}>
              {chart.map((a) => <Cell key={a.code} fill={BAR} />)}
            </Bar>
          </BarChart>
        </ChartCard>
      </div>
      <Card title={<span className="text-sm">{t("rpt.breachingNow", { n: s.breaching_now_total })}</span>}>
        {s.breaching_now.length === 0 ? <Empty>{t("rpt.noBreaches")}</Empty> : (
          <Table head={[t("c.reference"), t("c.app"), t("c.severity"), t("c.status"), t("c.title"), t("c.team"), t("c.overdue")]}>
            {s.breaching_now.map((b) => (
              <tr key={b.reference} className="hover:bg-slate-50">
                <td className={`${td} font-mono text-xs`}><Link to={`/incidents/${b.id}`} className="text-navy-800 hover:underline">{b.reference}</Link></td>
                <td className={td}>{b.application}</td>
                <td className={td}><SeverityBadge severity={b.severity} /></td>
                <td className={td}><StatusBadge status={b.status} /></td>
                <td className="px-3 py-1.5">{b.title}</td>
                <td className={td}>{b.assigned_team ?? "-"}</td>
                <td className={`${td} font-semibold text-red-700`}>{hours(b.overdue_minutes)}</td>
              </tr>
            ))}
          </Table>
        )}
        <p className="mt-2 text-xs text-slate-500">{label("SLA_BREACHED")}: {t("rpt.slaNote")}</p>
      </Card>
    </div>
  );
}

// ---- 3. trends ---------------------------------------------------------------------------

function Trends({ p }: { p: ManagementPack }) {
  const { t } = useI18n();
  const tr = p.trends;
  const g = tr.granularity === "week" ? t("ch.week") : t("ch.month");
  const data = tr.points.map((pt) => ({ ...pt, mttr_hours: pt.mttr_minutes == null ? null : +(pt.mttr_minutes / 60).toFixed(1) }));
  const created = data.reduce((n, d) => n + d.created, 0);
  const resolved = data.reduce((n, d) => n + d.resolved, 0);
  const breached = data.reduce((n, d) => n + d.sla_breached, 0);
  return (
    <div className="space-y-4">
      <Kpis items={[
        [t("c.created"), created.toLocaleString()],
        [t("c.resolved"), resolved.toLocaleString()],
        [t("c.slaBreached"), breached],
        [t("kpi.mttr"), hours(p.scorecard.totals.mttr_minutes)],
        [t("kpi.mtta"), hours(p.scorecard.totals.mtta_minutes)],
        [t("kpi.openP1"), p.scorecard.totals.open_p1],
      ]} />
      <ChartCard title={t("ch.volume", { g })} height={300}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="period" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip cursor={{ fill: "rgba(19,34,74,0.06)" }} />
          <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => <span style={{ color: "#52514e" }}>{v}</span>} />
          {(["P1", "P2", "P3", "P4"] as Severity[]).map((s, i) => (
            <Bar key={s} dataKey={s} stackId="sev" fill={SEVERITY_COLORS[s]} stroke="#ffffff" strokeWidth={1}
              radius={i === 3 ? [4, 4, 0, 0] : [0, 0, 0, 0]} maxBarSize={40} />
          ))}
        </BarChart>
      </ChartCard>
      <ChartCard title={t("ch.mttr", { g })} height={220}>
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="period" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} />
          <Tooltip formatter={(v) => [t("rpt.hours", { n: String(v) }), t("kpi.mttr")]} />
          <Line type="monotone" dataKey="mttr_hours" stroke={BAR} strokeWidth={2} dot={{ r: 3 }} connectNulls />
        </LineChart>
      </ChartCard>
      <Card>
        <Table head={[t("c.period"), t("c.created"), "P1", "P2", "P3", "P4", t("c.resolved"), t("c.slaBreached"), t("c.mttr")]}>
          {data.map((d) => (
            <tr key={d.period}>
              <td className={td}>{d.period}</td><td className={td}>{d.created}</td>
              <td className={td}>{d.P1}</td><td className={td}>{d.P2}</td><td className={td}>{d.P3}</td><td className={td}>{d.P4}</td>
              <td className={td}>{d.resolved}</td><td className={td}>{d.sla_breached}</td><td className={td}>{hours(d.mttr_minutes)}</td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}

// ---- 4. change risk ----------------------------------------------------------------------

function ChangeRisk({ p }: { p: ManagementPack }) {
  const { t, label } = useI18n();
  const c = p.change_risk;
  const chart = c.by_application.filter((a) => a.changes > 0);
  return (
    <div className="space-y-4">
      <Kpis items={[
        [t("kpi.changes"), c.totals.changes],
        [t("kpi.cfr"), pct(c.totals.change_failure_rate_pct)],
        [t("kpi.linked"), c.totals.linked_incidents],
        [t("c.failed"), c.by_application.reduce((n, a) => n + a.failed_or_rolled_back, 0)],
        [t("c.emergency"), c.by_application.reduce((n, a) => n + a.emergency, 0)],
        [t("c.highRisk"), c.by_application.reduce((n, a) => n + a.high_risk, 0)],
      ]} />
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title={t("ch.cfrByApp")} height={260}>
          <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="code" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} unit="%" />
            <Tooltip cursor={{ fill: "rgba(19,34,74,0.06)" }} formatter={(v) => [`${v}%`, t("c.cfr")]} labelFormatter={(code) => chart.find((a) => a.code === code)?.name ?? code} />
            <Bar dataKey="change_failure_rate_pct" fill={BAR} radius={[4, 4, 0, 0]} maxBarSize={36} />
          </BarChart>
        </ChartCard>
        <Card>
          <Table head={[t("c.app"), t("c.changes"), t("c.emergency"), t("c.highRisk"), t("c.failed"), t("c.withIncidents"), t("c.cfr")]}>
            {c.by_application.map((a) => (
              <tr key={a.code}>
                <td className={td}><b className="font-medium text-navy-900">{a.code}</b></td>
                <td className={td}>{a.changes}</td><td className={td}>{a.emergency}</td><td className={td}>{a.high_risk}</td>
                <td className={td}>{a.failed_or_rolled_back}</td><td className={td}>{a.changes_with_incidents}</td>
                <td className={td}>{pct(a.change_failure_rate_pct)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
      <Card title={<span className="text-sm">{t("rpt.topChanges")}</span>}>
        {c.top_changes.length === 0 ? <Empty>{t("rpt.none")}</Empty> : (
          <Table head={[t("c.change"), t("c.app"), t("c.title"), t("c.type"), t("c.risk"), t("c.status"), t("c.deployed"), t("c.linkedIncidents")]}>
            {c.top_changes.map((ch) => (
              <tr key={ch.reference}>
                <td className={`${td} font-mono text-xs`}>{ch.reference}</td><td className={td}>{ch.application}</td>
                <td className="px-3 py-1.5">{ch.title}</td><td className={td}>{label(ch.type)}</td><td className={td}>{label(ch.risk)}</td>
                <td className={td}>{label(ch.status)}</td><td className={td}>{formatTime(ch.deployed_at)}</td>
                <td className="px-3 py-1.5 font-mono text-xs">{ch.incidents.join(", ")}</td>
              </tr>
            ))}
          </Table>
        )}
        <p className="mt-2 text-xs text-slate-500">{c.definition}</p>
      </Card>
    </div>
  );
}

// ---- 5. problem management ---------------------------------------------------------------

function Problems({ p }: { p: ManagementPack }) {
  const { t, label } = useI18n();
  const pr = p.problems;
  return (
    <div className="space-y-4">
      <Kpis items={[
        [t("kpi.recurring"), pr.recurring_total],
        [t("kpi.reopened"), pr.reopened_total],
        [t("c.occurrences"), pr.recurring.reduce((n, r) => n + r.occurrences, 0)],
        [t("c.p1p2"), pr.recurring.reduce((n, r) => n + r.p1_p2, 0)],
        [t("c.open"), pr.recurring.reduce((n, r) => n + r.open, 0)],
        [t("kpi.applications"), new Set(pr.recurring.map((r) => r.application)).size],
      ]} />
      <Card title={<span className="text-sm">{t("rpt.recurring", { n: pr.recurring_total })}</span>}>
        {pr.recurring.length === 0 ? <Empty>{t("rpt.none")}</Empty> : (
          <Table head={[t("c.app"), t("c.category"), t("c.occurrences"), t("c.open"), t("c.p1p2"), t("c.mttr"), t("c.last"), t("c.latest")]}>
            {pr.recurring.map((r) => (
              <tr key={`${r.application}-${r.category}`} className="hover:bg-slate-50">
                <td className={td}><b className="font-medium text-navy-900">{r.application}</b> <span className="text-slate-500">{r.application_name}</span></td>
                <td className={td}>{label(r.category)}</td>
                <td className={`${td} font-semibold`}>{r.occurrences}</td>
                <td className={td}>{r.open}</td><td className={td}>{r.p1_p2}</td><td className={td}>{hours(r.mttr_minutes)}</td>
                <td className={td}>{formatTime(r.last_occurred_at)}</td>
                <td className="px-3 py-1.5 font-mono text-xs">{r.latest_references.join(", ")}</td>
              </tr>
            ))}
          </Table>
        )}
        <p className="mt-2 text-xs text-slate-500">{pr.note}</p>
      </Card>
      <Card title={<span className="text-sm">{t("rpt.reopenedList", { n: pr.reopened_total })}</span>}>
        {pr.reopened.length === 0 ? <Empty>{t("rpt.none")}</Empty> : (
          <Table head={[t("c.reference"), t("c.app"), t("c.severity"), t("c.title"), t("c.reopens")]}>
            {pr.reopened.map((r) => (
              <tr key={r.reference} className="hover:bg-slate-50">
                <td className={`${td} font-mono text-xs`}><Link to={`/incidents/${r.id}`} className="text-navy-800 hover:underline">{r.reference}</Link></td>
                <td className={td}>{r.application}</td><td className={td}><SeverityBadge severity={r.severity} /></td>
                <td className="px-3 py-1.5">{r.title}</td><td className={td}>{r.reopen_count}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}

