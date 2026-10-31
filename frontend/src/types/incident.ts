// Mirrors backend/app/schemas - keep in sync with the API.

export type Severity = "P1" | "P2" | "P3" | "P4";
export type Priority = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
export type IncidentStatus =
  | "OPEN"
  | "ASSIGNED"
  | "INVESTIGATING"
  | "ESCALATED"
  | "ON_HOLD"
  | "RESOLVED"
  | "CLOSED"
  | "REOPENED";
export type SlaState = "ON_TRACK" | "AT_RISK" | "BREACHED" | "MET";

export interface SlaClock {
  state: SlaState;
  target_minutes: number;
  due_at: string;
  elapsed_minutes: number;
  remaining_minutes: number;
  actual_minutes: number | null;
}

export interface Sla {
  severity: Severity;
  clock_started_at: string;
  response: SlaClock;
  resolution: SlaClock;
  is_breached: boolean;
  escalation_status: "NONE" | "RECOMMENDED" | "ESCALATED";
  note: string;
}

export interface ApplicationRef {
  id: number;
  code: string;
  name: string;
  business_criticality: "TIER_1" | "TIER_2" | "TIER_3";
}

export interface Incident {
  id: number;
  reference_number: string;
  title: string;
  description: string;
  application: ApplicationRef;
  application_name: string;
  severity: Severity;
  priority: Priority;
  category: string;
  status: IncidentStatus;
  assigned_team: string | null;
  assigned_engineer: string | null;
  business_impact: string | null;
  resolution_summary: string | null;
  reopen_count: number;
  started_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  sla: Sla | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface IncidentSummary {
  total_incidents: number;
  open_incidents: number;
  resolved_or_closed_incidents: number;
  p1_incidents: number;
  open_p1_incidents: number;
  reopened_incidents: number;
  sla_breached_incidents: number;
  sla_compliance_pct: number | null;
  mttr_minutes: number | null;
  generated_at: string;
}
