import { BarChart3, Bot, LayoutDashboard, Landmark, ListChecks, Network, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { LanguageToggle, useI18n } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { DEMO_USERS, type Identity } from "../services/identity";

const NAV: { to: string; label: MessageKey; icon: typeof Bot; end: boolean }[] = [
  { to: "/", label: "nav.dashboard", icon: LayoutDashboard, end: true },
  { to: "/incidents", label: "nav.incidents", icon: ListChecks, end: false },
  { to: "/investigations", label: "nav.investigations", icon: Bot, end: false },
  { to: "/reports", label: "nav.reports", icon: BarChart3, end: false },
  { to: "/architecture", label: "nav.architecture", icon: Network, end: false },
];
const ROLE_LABEL: Record<string, MessageKey> = { ENGINEER: "users.engineer", INCIDENT_MANAGER: "users.manager", VIEWER: "users.viewer" };

export default function Layout({ identity, onIdentityChange, children }: { identity: Identity; onIdentityChange: (identity: Identity) => void; children: ReactNode }) {
  const { t } = useI18n();
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
            onChange={(e) => onIdentityChange(DEMO_USERS.find((u) => u.name === e.target.value)!)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            {DEMO_USERS.map((u) => (
              <option key={u.name} value={u.name}>
                {t(ROLE_LABEL[u.role])}
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
