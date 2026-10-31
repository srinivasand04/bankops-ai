import axios from "axios";

import type { Incident, IncidentSummary, Page } from "../types/incident";

// Demo mode identity (backend AUTH_ENABLED=false). Replaced by real auth in a later phase.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api",
  headers: { "X-User-Name": "demo.manager", "X-User-Role": "INCIDENT_MANAGER" },
  timeout: 15000,
});

export const incidentApi = {
  list: (params: Record<string, unknown> = {}) =>
    api.get<Page<Incident>>("/incidents", { params, paramsSerializer: { indexes: null } }).then((r) => r.data),
  get: (id: number) => api.get<Incident>(`/incidents/${id}`).then((r) => r.data),
};

export const analyticsApi = {
  summary: () => api.get<IncidentSummary>("/analytics/incident-summary").then((r) => r.data),
};

export const healthApi = {
  check: () => api.get<{ status: string; database: string }>("/health").then((r) => r.data),
};
