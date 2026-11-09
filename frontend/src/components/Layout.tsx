import { BarChart3, Bot, FlaskConical, LayoutDashboard, Landmark, ListChecks, Network, UserRound, Users } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { LanguageToggle, useI18n } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { useApi } from "../hooks/useApi";
import { ROLE_KEY } from "../pages/UsersPage";
import { usersApi } from "../services/api";
import { DEFAULT_IDENTITY, type Identity } from "../services/identity";

// Default role users are named after their role: show just the (translated) role for them
const ROLE_NAMES = new Set(["Engineer", "Incident manager", "Viewer", "Administrator"]);

const NAV: { to: string; label: MessageKey; icon: typeof Bot; end: boolean }[] = [
  { to: "/", label: "nav.dashboard", icon: LayoutDashboard, end: true },
  { to: "/incidents", label: "nav.incidents", icon: ListChecks, end: false },
  { to: "/investigations", label: "nav.investigations", icon: Bot, end: false },
  { to: "/reports", label: "nav.reports", icon: BarChart3, end: false },
  { to: "/ml", label: "nav.ml", icon: FlaskConical, end: false },
  { to: "/users", label: "nav.users", icon: Users, end: false },
  { to: "/architecture", label: "nav.architecture", icon: Network, end: false },
];

export default function Layout({ identity, onIdentityChange, usersVersion, children }: { identity: Identity; onIdentityChange: (identity: Identity) => void; usersVersion: number; children: ReactNode }) {
  const { t } = useI18n();
  // Active users for the picker; retried every 5 s until the (possibly sleeping) API answers
  const users = useApi(() => usersApi.list(false), [usersVersion], { pollMs: 5000, keepPolling: (d) => !d });
  const list = users.data ?? [];

  // Keep the chosen identity in step with the database: role changes apply, removed users fall back to the admin
  useEffect(() => {
    if (!users.data) return;
    const me = users.data.find((u) => u.username === identity.name);
    const fallback = users.data.find((u) => u.username === DEFAULT_IDENTITY.name) ?? users.data[0];
    const next = me ?? fallback;
    if (next && (next.username !== identity.name || next.role !== identity.role || next.full_name !== identity.label)) {
      onIdentityChange({ name: next.username, role: next.role, label: next.full_name });
    }
  }, [users.data, identity, onIdentityChange]);
  return (
    <div className="min-h-screen md:flex">
      <aside className="no-print bg-navy-950 text-slate-200 md:w-56 md:shrink-0">
        <div className="flex items-center gap-2 px-4 py-4 text-white">
          <Landmark size={22} aria-hidden="true" />
          <div>
            <div className="font-semibold leading-tight">BankOps AI</div>
            <div className="text-xs text-slate-400">{t("app.tagline")}</div>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-3 md:flex-col md:pb-0">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive ? "bg-navy-800 text-white" : "hover:bg-navy-900"}`
              }
            >
              <Icon size={16} aria-hidden="true" />
              {t(label)}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="no-print flex flex-wrap items-center justify-end gap-2 border-b border-slate-200 bg-white px-4 py-2 text-sm">
          <LanguageToggle />
          <span className="mx-1 h-5 w-px bg-slate-200" aria-hidden="true" />
          <UserRound size={16} className="text-slate-500" aria-hidden="true" />
          <label htmlFor="identity" className="text-slate-500">
            {t("header.actingAs")}
          </label>
          <select
            id="identity"
            value={identity.name}
            onChange={(e) => {
              const u = list.find((x) => x.username === e.target.value);
              if (u) onIdentityChange({ name: u.username, role: u.role, label: u.full_name });
            }}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            {list.length === 0 && <option value={identity.name}>{identity.label}</option>}
            {list.map((u) => (
              <option key={u.username} value={u.username}>
                {ROLE_NAMES.has(u.full_name) ? t(ROLE_KEY[u.role]) : `${u.full_name} - ${t(ROLE_KEY[u.role])}`}
              </option>
            ))}
          </select>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
        <footer className="no-print px-4 pb-6 text-center text-xs text-slate-500">
          {t("footer.disclaimer")}
        </footer>
      </div>
    </div>
  );
}
