// Demo identity (backend AUTH_ENABLED=false): the API reads X-User-Name / X-User-Role headers.
// Switching user in the header lets you show who may do what (engineers cannot approve AI output).
import type { Role } from "../types/incident";

export interface Identity {
  name: string;
  role: Role;
  label: string;
}

export const DEMO_USERS: Identity[] = [
  { name: "engineer", role: "ENGINEER", label: "Engineer" },
  { name: "incident.manager", role: "INCIDENT_MANAGER", label: "Incident manager" },
  { name: "risk.viewer", role: "VIEWER", label: "Viewer (read only)" },
];

const KEY = "bankops.identity";

export function loadIdentity(): Identity {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null") as Identity | null;
    const known = DEMO_USERS.find((u) => u.name === saved?.name);
    if (known) return known;
  } catch {
    // storage unavailable (private window) - fall back to the default user
  }
  return DEMO_USERS[1];
}

export function saveIdentity(identity: Identity): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(identity));
  } catch {
    // not persisted; the choice still applies for this page load
  }
}

let current = loadIdentity();

export const getIdentity = () => current;
export function setIdentity(identity: Identity) {
  current = identity;
  saveIdentity(identity);
}

const RANK: Record<Role, number> = { VIEWER: 0, ENGINEER: 1, INCIDENT_MANAGER: 2, ADMIN: 3 };
export const canAct = (role: Role, minimum: Role) => RANK[role] >= RANK[minimum];
