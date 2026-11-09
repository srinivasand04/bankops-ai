import { ShieldCheck, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button, Card, ErrorBanner, Field, inputClass } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useI18n } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { errorMessage, usersApi, type AppUser } from "../services/api";
import { canAct, type Identity } from "../services/identity";
import type { Role } from "../types/incident";

export const ROLES: Role[] = ["VIEWER", "ENGINEER", "INCIDENT_MANAGER", "ADMIN"];
export const ROLE_KEY: Record<Role, MessageKey> = {
  VIEWER: "users.viewer", ENGINEER: "users.engineer", INCIDENT_MANAGER: "users.manager", ADMIN: "users.admin",
};

/** Administrators add people and decide what each one may do. Everyone else sees the list read-only. */
export default function UsersPage({ identity, onUsersChanged }: { identity: Identity; onUsersChanged: () => void }) {
  const { t } = useI18n();
  const users = useApi(() => usersApi.list(true));
  const [error, setError] = useState<string | null>(null);
  const isAdmin = canAct(identity.role, "ADMIN");

  const update = async (u: AppUser, change: Partial<Pick<AppUser, "role" | "is_active">>) => {
    setError(null);
    try {
      await usersApi.update(u.id, change);
      users.reload();
      onUsersChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-navy-900">{t("um.title")}</h1>
        <p className="text-sm text-slate-600">{t("um.subtitle")}</p>
      </div>

      {!isAdmin && <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200">{t("um.readOnly")}</p>}
      {isAdmin && <AddUser onAdded={() => { users.reload(); onUsersChanged(); }} />}

      <ErrorBanner message={error ?? users.error} onClose={() => setError(null)} />
      <Card title={t("um.list", { n: users.data?.length ?? 0 })}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>{[t("um.name"), t("um.username"), t("um.team"), t("um.email"), t("um.role"), t("um.status"), t("um.createdBy")].map((h) => (
                <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>
              ))}</tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.data?.map((u) => {
                const self = u.username === identity.name;
                return (
                  <tr key={u.id} className={u.is_active ? "" : "bg-slate-50 text-slate-400"}>
                    <td className="whitespace-nowrap px-3 py-2 font-medium text-navy-900">
                      {u.full_name}
                      {self && <span className="ml-2 rounded bg-navy-900 px-1.5 py-0.5 text-xs font-semibold text-white">{t("um.you")}</span>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{u.username}</td>
                    <td className="whitespace-nowrap px-3 py-2">{u.team ?? "-"}</td>
                    <td className="whitespace-nowrap px-3 py-2">{u.email ?? "-"}</td>
                    <td className="whitespace-nowrap px-3 py-2">
                      {isAdmin ? (
                        <select aria-label={t("um.role")} value={u.role} onChange={(e) => update(u, { role: e.target.value as Role })} className={`${inputClass} w-auto py-1`}>
                          {ROLES.map((r) => <option key={r} value={r}>{t(ROLE_KEY[r])}</option>)}
                        </select>
                      ) : (
                        <span className="inline-flex items-center gap-1">{u.role === "ADMIN" && <ShieldCheck size={14} aria-hidden="true" />}{t(ROLE_KEY[u.role])}</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <span className={`mr-2 rounded px-1.5 py-0.5 text-xs font-semibold ${u.is_active ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-600"}`}>
                        {u.is_active ? t("um.active") : t("um.inactive")}
                      </span>
                      {isAdmin && !self && (
                        <button onClick={() => update(u, { is_active: !u.is_active })} className="text-xs font-medium text-navy-800 hover:underline">
                          {u.is_active ? t("um.deactivate") : t("um.activate")}
                        </button>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{u.created_by}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title={t("um.rolesTitle")}>
        <ul className="grid gap-2 text-sm sm:grid-cols-2">
          {ROLES.map((r) => (
            <li key={r} className="rounded-md bg-slate-50 p-3">
              <b className="font-medium text-navy-900">{t(ROLE_KEY[r])}</b>
              <p className="mt-0.5 text-slate-600">{t(`um.can.${r}` as MessageKey)}</p>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-slate-500">{t("um.demoNote")}</p>
      </Card>
    </div>
  );
}

function AddUser({ onAdded }: { onAdded: () => void }) {
  const { t } = useI18n();
  const empty = { username: "", full_name: "", email: "", team: "", role: "ENGINEER" as Role };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (k: keyof typeof empty, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await usersApi.create({ ...form, username: form.username.trim().toLowerCase(), full_name: form.full_name.trim(),
        email: form.email.trim() || null, team: form.team.trim() || null });
      setForm(empty);
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title={<span className="flex items-center gap-2"><UserPlus size={16} aria-hidden="true" /> {t("um.add")}</span>}>
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-3 lg:grid-cols-6 lg:items-end">
        <div className="lg:col-span-2"><Field label={t("um.name")}><input required value={form.full_name} onChange={(e) => set("full_name", e.target.value)} placeholder="Julie Martin" className={inputClass} /></Field></div>
        <Field label={t("um.username")} hint={t("um.usernameHint")}><input required value={form.username} onChange={(e) => set("username", e.target.value)} placeholder="j.martin" className={inputClass} /></Field>
        <Field label={t("um.team")}><input value={form.team} onChange={(e) => set("team", e.target.value)} className={inputClass} /></Field>
        <Field label={t("um.email")}><input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} className={inputClass} /></Field>
        <Field label={t("um.role")}>
          <select value={form.role} onChange={(e) => set("role", e.target.value)} className={inputClass}>
            {ROLES.map((r) => <option key={r} value={r}>{t(ROLE_KEY[r])}</option>)}
          </select>
        </Field>
        <div className="md:col-span-3 lg:col-span-6 flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={saving}><UserPlus size={15} aria-hidden="true" />{saving ? t("um.adding") : t("um.addButton")}</Button>
          <ErrorBanner message={error} onClose={() => setError(null)} />
        </div>
      </form>
    </Card>
  );
}
