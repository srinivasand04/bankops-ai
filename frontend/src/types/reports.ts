import type { IncidentStatus, Severity } from "./incident";

type Rag = "RED" | "AMBER" | "GREEN";
interface SlaCounts { met: number; breached: number; pending: number; compliance_pct: number | null }

export interface ManagementPack {
  period: { days: number; from: string; to: string; generated_at: string };
  scorecard: {
    totals: {
      applications: number; incidents: number; open: number; p1: number; open_p1: number; sla_compliance_pct: number | null;
      breaching_now: number; mttr_minutes: number | null; mtta_minutes: number | null; changes: number; rag: Partial<Record<Rag, number>>;
    };
    applications: {
      application_id: number; code: string; name: string; tier: string; health: string; owner_team: string | null;
      incidents: number; open: number; p1: number; p2: number; open_p1: number; sla_compliance_pct: number | null;
      sla_breached: number; breaching_now: number; mttr_minutes: number | null; mtta_minutes: number | null; reopened: number;
      changes: number; failed_changes: number; change_linked_incidents: number; top_category: string | null; rag: Rag;
    }[];
    rag_rules: string;
  };
  sla: {
    overall: { response: SlaCounts; resolution: SlaCounts };
    by_severity: { severity: Severity; incidents: number; response_target_minutes: number; resolution_target_minutes: number; response: SlaCounts; resolution: SlaCounts }[];
    by_application: ({ code: string; name: string; tier: string } & SlaCounts)[];
    breaching_now: { id: number; reference: string; application: string; severity: Severity; status: IncidentStatus; title: string; assigned_team: string | null; overdue_minutes: number }[];
    breaching_now_total: number;
    note: string;
  };
  trends: {
    granularity: "week" | "month";
    points: { period: string; created: number; resolved: number; sla_breached: number; P1: number; P2: number; P3: number; P4: number; mttr_minutes: number | null }[];
  };
  change_risk: {
    totals: { changes: number; change_failure_rate_pct: number | null; linked_incidents: number };
    by_application: { code: string; name: string; tier: string; changes: number; emergency: number; high_risk: number; failed_or_rolled_back: number; changes_with_incidents: number; linked_incidents: number; change_failure_rate_pct: number | null }[];
    top_changes: { reference: string; application: string; title: string; type: string; risk: string; status: string; deployed_at: string; incidents: string[] }[];
    definition: string;
  };
  problems: {
    threshold: number;
    recurring: { application: string; application_name: string; category: string; occurrences: number; open: number; p1_p2: number; mttr_minutes: number | null; last_occurred_at: string; latest_references: string[] }[];
    recurring_total: number;
    reopened: { id: number; reference: string; application: string; severity: Severity; title: string; reopen_count: number }[];
    reopened_total: number;
    note: string;
  };
}
