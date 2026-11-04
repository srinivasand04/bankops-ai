import { Bot, LayoutDashboard, Landmark, ListChecks, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { DEMO_USERS, type Identity } from "../services/identity";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/incidents", label: "Incidents", icon: ListChecks, end: false },
  { to: "/investigations", label: "AI investigations", icon: Bot, end: false },
];

export default function Layout({ identity, onIdentityChange, children }: { identity: Identity; onIdentityChange: (identity: Identity) => void; children: ReactNode }) {
  return (
    <div className="min-h-screen md:flex">
      <aside className="bg-navy-950 text-slate-200 md:w-56 md:shrink-0">
        <div className="flex items-center gap-2 px-4 py-4 text-white">
          <Landmark size={22} aria-hidden="true" />
          <div>
            <div className="font-semibold leading-tight">BankOps AI</div>
            <div className="text-xs text-slate-400">Incident intelligence</div>
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
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="flex flex-wrap items-center justify-end gap-2 border-b border-slate-200 bg-white px-4 py-2 text-sm">
          <UserRound size={16} className="text-slate-500" aria-hidden="true" />
          <label htmlFor="identity" className="text-slate-500">
            Acting as
          </label>
          <select
            id="identity"
            value={identity.name}
            onChange={(e) => onIdentityChange(DEMO_USERS.find((u) => u.name === e.target.value)!)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            {DEMO_USERS.map((u) => (
              <option key={u.name} value={u.name}>
                {u.label}
              </option>
            ))}
          </select>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
        <footer className="px-4 pb-6 text-center text-xs text-slate-500">
          Synthetic data only. SLA targets are demonstration values. AI output is advisory and always needs human review.
        </footer>
      </div>
    </div>
  );
}
