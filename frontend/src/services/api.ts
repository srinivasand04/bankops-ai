import axios from "axios";

import type { ActiveCalendar, CalendarPeriod, CalendarPeriodInput } from "../types/calendar";
import type {
  AiStatus,
  Application,
  ApplicationDetail,
  CapaAction,
  Incident,
  IncidentDetail,
  IncidentSummary,
  Investigation,
  Page,
  Rca,
  ReferenceData,
  RootCause,
  TimelineEvent,
} from "../types/incident";
import type { MlPrediction, MlRun, MlTask, ScoredChange } from "../types/ml";
import type { ManagementPack } from "../types/reports";
import { getIdentity } from "./identity";

export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api", timeout: 30000 });

api.interceptors.request.use((config) => {
  const user = getIdentity();
  config.headers.set("X-User-Name", user.name);
  config.headers.set("X-User-Role", user.role);
  return config;
});

/** The backend returns {"error": {"code", "message", "details"}} - surface the message. */
export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const body = err.response?.data as { error?: { message?: string; details?: { errors?: { field: string; message: string }[] } } };
    const fieldErrors = body?.error?.details?.errors;
    if (fieldErrors?.length) return fieldErrors.map((e) => `${e.field}: ${e.message}`).join("; ");
    if (body?.error?.message) return body.error.message;
    if (!err.response) return "Backend not reachable - is it running on port 8000?";
    return `${err.response.status} ${err.response.statusText}`;
  }
  return String(err);
}

const data = <T,>(p: Promise<{ data: T }>) => p.then((r) => r.data);

export interface NewIncident {
  title: string;
  description: string;
  application_id: number;
  severity: string;
  category: string;
  priority?: string;
  business_impact?: string;
  assigned_team?: string;
  assigned_engineer?: string;
}

export const incidentApi = {
  list: (params: Record<string, unknown> = {}) =>
    data(api.get<Page<Incident>>("/incidents", { params, paramsSerializer: { indexes: null } })),
  get: (id: number) => data(api.get<IncidentDetail>(`/incidents/${id}`)),
  create: (body: NewIncident) => data(api.post<IncidentDetail>("/incidents", body)),
  changeStatus: (id: number, status: string, extra: { note?: string; resolution_summary?: string } = {}) =>
    data(api.patch<IncidentDetail>(`/incidents/${id}/status`, { status, ...extra })),
  assign: (id: number, assigned_team: string, assigned_engineer?: string) =>
    data(api.patch<IncidentDetail>(`/incidents/${id}/assign`, { assigned_team, assigned_engineer: assigned_engineer || null })),
  timeline: (id: number) => data(api.get<TimelineEvent[]>(`/incidents/${id}/timeline`)),
  addEvent: (id: number, event_type: string, description: string) =>
    data(api.post<TimelineEvent>(`/incidents/${id}/events`, { event_type, description })),
  rca: (id: number) => data(api.get<Rca>(`/incidents/${id}/rca`)),
  reviewRootCause: (rootCauseId: number, decision: "CONFIRM" | "REJECT", review_notes?: string) =>
    data(api.post<RootCause>(`/root-causes/${rootCauseId}/review`, { decision, review_notes })),
  updateAction: (actionId: number, status: CapaAction["status"]) =>
    data(api.patch<CapaAction>(`/actions/${actionId}`, { status })),
};

export const referenceApi = {
  applications: () => data(api.get<Application[]>("/applications")),
  application: (id: number) => data(api.get<ApplicationDetail>(`/applications/${id}`)),
  referenceData: () => data(api.get<ReferenceData>("/reference-data")),
};

export const analyticsApi = {
  summary: () => data(api.get<IncidentSummary>("/analytics/incident-summary")),
};

export const aiApi = {
  status: () => data(api.get<AiStatus>("/ai/status")),
  analyze: (incidentId: number, focus?: string) =>
    data(api.post<Investigation>(`/ai/incidents/${incidentId}/analyze`, focus ? { focus } : undefined)),
  investigate: (incidentId: number, focus?: string) =>
    data(api.post<Investigation>(`/ai/incidents/${incidentId}/investigate`, focus ? { focus } : undefined)),
  list: (params: Record<string, unknown> = {}) => data(api.get<Investigation[]>("/ai/investigations", { params })),
  forIncident: (incidentId: number) => data(api.get<Investigation[]>(`/ai/incidents/${incidentId}/investigations`)),
  get: (id: number) => data(api.get<Investigation>(`/ai/investigations/${id}`)),
  review: (id: number, decision: "APPROVE" | "REJECT", review_notes: string, apply_hypotheses = true, apply_actions = true) =>
    data(api.post<Investigation>(`/ai/investigations/${id}/review`, { decision, review_notes: review_notes || null, apply_hypotheses, apply_actions })),
};

export const reportsApi = {
  // Building all five reports takes a few seconds on a large dataset
  managementPack: (days: number) => data(api.get<ManagementPack>("/reports/management-pack", { params: { days }, timeout: 60000 })),
};

export interface AppUser {
  id: number;
  username: string;
  full_name: string;
  email: string | null;
  role: import("../types/incident").Role;
  team: string | null;
  is_active: boolean;
  created_by: string;
}

export const usersApi = {
  list: (includeInactive = true) => data(api.get<AppUser[]>("/users", { params: { include_inactive: includeInactive } })),
  create: (body: Omit<AppUser, "id" | "is_active" | "created_by">) => data(api.post<AppUser>("/users", body)),
  update: (id: number, body: Partial<Omit<AppUser, "id" | "username" | "created_by">>) => data(api.patch<AppUser>(`/users/${id}`, body)),
};

export const mlApi = {
  tasks: () => data(api.get<MlTask[]>("/ml/tasks")),
  runs: (task?: string) => data(api.get<MlRun[]>("/ml/runs", { params: { task } })),
  train: (tasks: string[] | "all") => data(api.post<{ queued: string[] }>("/ml/train", { tasks })),
  incidentPredictions: (id: number, refresh = false) =>
    data(api.get<MlPrediction[]>(`/ml/incidents/${id}/predictions`, { params: { refresh }, timeout: 60000 })),
  changes: (limit = 15) => data(api.get<ScoredChange[]>("/ml/changes", { params: { limit }, timeout: 60000 })),
};

export const healthApi = {
  check: () => data(api.get<{ status: string; database: string }>("/health")),
};

export const calendarApi = {
  list: (params: { start?: string; end?: string; application?: string; period_type?: string[] } = {}) =>
    data(api.get<CalendarPeriod[]>("/business-calendar", { params, paramsSerializer: { indexes: null } })),
  active: (applicationId: number, severity?: string) =>
    data(api.get<ActiveCalendar>("/business-calendar/active", { params: { application_id: applicationId, severity } })),
  create: (body: CalendarPeriodInput) => data(api.post<CalendarPeriod>("/business-calendar", body)),
  remove: (id: number) => api.delete(`/business-calendar/${id}`),
};
