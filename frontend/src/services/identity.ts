// Who is using the tool (demo mode: no passwords). The API reads X-User-Name; for users stored by an
// administrator the role always comes from the database, so the role kept here is only for the UI.
import type { Role } from "../types/incident";

export interface Identity {
  name: string;
  role: Role;
  label: string;
}

export const DEFAULT_IDENTITY: Identity = { name: "srinivasan.d", role: "ADMIN", label: "Srinivasan Dhakshanamoorthy" };

const KEY = "bankops.identity";

export function loadIdentity(): Identity {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null") as Identity | null;
    if (saved?.name && saved.role) return saved;
  } catch {
    // storage unavailable (private window) - fall back to the default user
  }
  return DEFAULT_IDENTITY;
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
