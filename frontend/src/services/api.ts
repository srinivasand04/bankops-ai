import axios from "axios";

import type {
  AiStatus,
  Application,
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
  referenceData: () => data(api.get<ReferenceData>("/reference-data")),
};

export const analyticsApi = {
  summary: () => data(api.get<IncidentSummary>("/analytics/incident-summary")),
};

export const aiApi = {
  status: () => data(api.get<AiStatus>("/ai/status")),
  analyze: (incidentId: number, focus?: string) =>
    data(api.post<Investigation>(`/ai/incidents/${incidentId}/analyze`, focus ? { focus } : undefined)),
  list: (params: Record<string, unknown> = {}) => data(api.get<Investigation[]>("/ai/investigations", { params })),
  forIncident: (incidentId: number) => data(api.get<Investigation[]>(`/ai/incidents/${incidentId}/investigations`)),
  get: (id: number) => data(api.get<Investigation>(`/ai/investigations/${id}`)),
  review: (id: number, decision: "APPROVE" | "REJECT", review_notes: string, apply_hypotheses = true, apply_actions = true) =>
    data(api.post<Investigation>(`/ai/investigations/${id}/review`, { decision, review_notes: review_notes || null, apply_hypotheses, apply_actions })),
};

export const healthApi = {
  check: () => data(api.get<{ status: string; database: string }>("/health")),
};
