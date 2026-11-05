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
export type Role = "VIEWER" | "ENGINEER" | "INCIDENT_MANAGER" | "ADMIN";
export type Source = "HUMAN" | "AI" | "SYSTEM";

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

export interface Application extends ApplicationRef {
  description: string | null;
  business_service: string | null;
  technology_stack: string | null;
  owner_team: string | null;
  health_status: "HEALTHY" | "DEGRADED" | "DOWN" | "UNKNOWN";
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
  created_by: string;
  data_source: string;
  started_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  sla: Sla | null;
}

export interface IncidentDetail extends Incident {
  allowed_transitions: IncidentStatus[];
  root_cause_count: number;
  open_action_count: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface TimelineEvent {
  id: number;
  event_type: string;
  description: string;
  details: Record<string, unknown> | null;
  source: Source;
  created_by: string;
  created_at: string;
}

export interface RootCause {
  id: number;
  description: string;
  category: string | null;
  status: "HYPOTHESIS" | "UNDER_REVIEW" | "CONFIRMED" | "REJECTED";
  source: Source;
  confidence: number | null;
  supporting_evidence: string[];
  missing_evidence: string[];
  created_by: string;
  confirmed_by: string | null;
  review_notes: string | null;
}

export interface CapaAction {
  id: number;
  action_type: "CORRECTIVE" | "PREVENTIVE";
  description: string;
  assigned_team: string | null;
  assigned_owner: string | null;
  due_date: string | null;
  status: "OPEN" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
  is_overdue: boolean;
  source: Source;
}

export interface Rca {
  incident_reference: string;
  confirmed_root_causes: RootCause[];
  hypotheses: RootCause[];
  rejected_root_causes: RootCause[];
  corrective_actions: CapaAction[];
  preventive_actions: CapaAction[];
  related_changes: {
    id: number;
    link_status: string;
    minutes_from_deployment_to_incident: number | null;
    change: { change_reference: string; title: string; version: string | null };
  }[];
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

export interface ReferenceData {
  severities: { code: Severity; label: string; criteria: string[]; response_target_minutes: number; resolution_target_minutes: number }[];
  priorities: Priority[];
  categories: string[];
  statuses: IncidentStatus[];
  sla_disclaimer: string;
}

// ---- AI --------------------------------------------------------------------------------

export type InvestigationStatus = "PENDING" | "RUNNING" | "AWAITING_REVIEW" | "APPROVED" | "REJECTED" | "FAILED";

export interface AnalysisReport {
  summary: string;
  confirmed_facts: { statement: string; evidence_ids: string[] }[];
  unverified_statements: string[];
  root_cause_hypotheses: {
    description: string;
    category: string;
    confidence: number;
    supporting_evidence_ids: string[];
    contradicting_evidence_ids: string[];
    missing_evidence: string[];
    verification_steps: string[];
  }[];
  affected_services: { application_code: string; impact: string; evidence_ids: string[] }[];
  business_impact: {
    summary: string;
    customer_impact: string;
    regulatory_or_financial_exposure: string;
    assessed_severity: Severity;
    severity_rationale: string;
  };
  recommended_actions: {
    action_type: "CORRECTIVE" | "PREVENTIVE";
    description: string;
    owner_team: string;
    urgency: "IMMEDIATE" | "SHORT_TERM" | "LONG_TERM";
    requires_human_approval: boolean;
    approval_reason: string | null;
  }[];
  escalation: { recommended: boolean; reason: string };
  missing_information: string[];
  overall_confidence: "LOW" | "MEDIUM" | "HIGH";
  guardrail_notes: string[];
  disclaimer: string;
  context_summary?: Record<string, string | number>;
  applied?: { root_causes: number; actions: number };
}

export interface Investigation {
  id: number;
  incident_id: number | null;
  incident_reference: string | null;
  status: InvestigationStatus;
  request_text: string;
  model_name: string | null;
  report: AnalysisReport | null;
  error_message: string | null;
  requested_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  created_at: string;
  completed_at: string | null;
  executions: {
    agent_name: string;
    status: string;
    input_tokens: number | null;
    output_tokens: number | null;
    started_at: string;
    completed_at: string | null;
  }[];
}

export interface AiStatus {
  provider: "anthropic" | "ollama" | "groq";
  model: string;
  ready: boolean;
  detail: string;
  cost: string;
  daily_limit: number | null;
  runs_left_today: number | null;
}
