import { CalendarPlus, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { translatePeriodText } from "../components/PriorityReason";
import { Button, Card, Empty, ErrorBanner, Field, inputClass } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { currentLocale, useI18n } from "../i18n";
import { calendarApi, errorMessage, referenceApi } from "../services/api";
import { canAct, type Identity } from "../services/identity";
import { PERIOD_TYPES, type CalendarPeriod, type CalendarPeriodType } from "../types/calendar";

const DAY = 86_400_000;
const TYPE_STYLE: Record<CalendarPeriodType, string> = {
  MONTH_END_CLOSE: "bg-indigo-50 text-indigo-800 ring-indigo-200",
  QUARTER_END_CLOSE: "bg-violet-50 text-violet-800 ring-violet-200",
  YEAR_END_CLOSE: "bg-purple-50 text-purple-800 ring-purple-200",
  PAYROLL: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  REGULATORY_DEADLINE: "bg-red-50 text-red-800 ring-red-200",
  PEAK_PERIOD: "bg-amber-50 text-amber-900 ring-amber-200",
  BANK_HOLIDAY: "bg-slate-100 text-slate-700 ring-slate-300",
};

function day(iso: string): string {
  return new Date(iso).toLocaleDateString(currentLocale(), { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });
}

/** Last day of a period (ends_at is exclusive). */
function lastDay(p: CalendarPeriod): string {
  return day(new Date(new Date(p.ends_at).getTime() - 1).toISOString());
}

/** Business calendar: periods when incidents on some applications get +1 priority (holidays are context only). */
export default function CalendarPage({ identity }: { identity: Identity }) {
  const { t, label, lang } = useI18n();
  const [application, setApplication] = useState("");
  const [type, setType] = useState("");
  const [error, setError] = useState<string | null>(null);
  const isAdmin = canAct(identity.role, "ADMIN");
  const apps = useApi(() => referenceApi.applications());
  const periods = useApi(
    () =>
      calendarApi.list({
        start: new Date(Date.now() - 30 * DAY).toISOString(),
        end: new Date(Date.now() + 120 * DAY).toISOString(),
        application: application || undefined,
        period_type: type ? [type] : undefined,
      }),
    [application, type],
  );
  const activeIds = useMemo(() => {
    const now = Date.now();
    return new Set(
      (periods.data ?? [])
        .filter((p) => new Date(p.starts_at).getTime() <= now && now < new Date(p.ends_at).getTime())
        .map((p) => p.id),
    );
  }, [periods.data]);
  const activeNow = (periods.data ?? []).filter((p) => activeIds.has(p.id));

  const remove = async (p: CalendarPeriod) => {
    if (!window.confirm(t("cal.confirmDelete", { name: p.name }))) return;
    setError(null);
    try {
      await calendarApi.remove(p.id);
      periods.reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-navy-900">{t("cal.title")}</h1>
        <p className="text-sm text-slate-600">{t("cal.subtitle")}</p>
      </div>

      <div className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-xs font-medium uppercase text-slate-500">{t("cal.activeNow")}</p>
        {activeNow.length === 0 ? (
          <p className="mt-1 text-sm text-slate-600">{t("cal.noneActive")}</p>
        ) : (
          <ul className="mt-1 flex flex-wrap gap-2">
            {activeNow.map((p) => (
              <li key={p.id} className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${TYPE_STYLE[p.period_type]}`}>
                {translatePeriodText(p.name, lang)} · {p.raises_priority ? t("cal.plusOne") : t("cal.contextOnly")}
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="rounded-md bg-sky-50 p-3 text-sm text-sky-900 ring-1 ring-sky-200">{t("cal.rule")}</p>

      {isAdmin ? (
        <AddPeriod apps={apps.data?.map((a) => a.code) ?? []} onAdded={periods.reload} />
      ) : (
        <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200">{t("cal.readOnly")}</p>
      )}

      <ErrorBanner message={error ?? periods.error} onClose={() => setError(null)} />

      <Card
        title={t("cal.list", { n: periods.data?.length ?? 0 })}
        actions={
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
            <select aria-label={t("cal.application")} className={`${inputClass} sm:w-56`} value={application} onChange={(e) => setApplication(e.target.value)}>
              <option value="">{t("cal.allApps")}</option>
              {apps.data?.map((a) => (
                <option key={a.id} value={a.code}>
                  {a.code} - {a.name}
                </option>
              ))}
            </select>
            <select aria-label={t("cal.type")} className={`${inputClass} sm:w-48`} value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">{t("cal.allTypes")}</option>
              {PERIOD_TYPES.map((pt) => (
                <option key={pt} value={pt}>
                  {label(pt)}
                </option>
              ))}
            </select>
          </div>
        }
      >
        {periods.data && periods.data.length === 0 ? (
          <Empty>{t("cal.empty")}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  {[t("cal.period"), t("cal.type"), t("cal.dates"), t("cal.applications"), t("cal.effect")].map((h) => (
                    <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                  {isAdmin && (
                    <th className="px-3 py-2">
                      <span className="sr-only">{t("cal.delete")}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {periods.data?.map((p) => {
                  const active = activeIds.has(p.id);
                  const first = day(p.starts_at);
                  const last = lastDay(p);
                  return (
                    <tr key={p.id} className={active ? "bg-amber-50/60" : ""}>
                      <td className="min-w-[16rem] px-3 py-2">
                        <div className="font-medium text-navy-900">{translatePeriodText(p.name, lang)}</div>
                        {p.description && <div className="text-xs text-slate-500">{translatePeriodText(p.description, lang)}</div>}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${TYPE_STYLE[p.period_type]}`}>{label(p.period_type)}</span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-slate-700">
                        {first === last ? first : `${first} → ${last}`}
                        {active && <span className="ml-2 text-xs font-semibold text-amber-700">{t("cal.now")}</span>}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-slate-600">
                        {p.application_codes.length ? p.application_codes.join(", ") : t("cal.allApps")}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        {p.raises_priority ? (
                          <span className="font-medium text-amber-800">{t("cal.plusOne")}</span>
                        ) : (
                          <span className="text-slate-500">{t("cal.contextOnly")}</span>
                        )}
                      </td>
                      {isAdmin && (
                        <td className="px-3 py-2 text-right">
                          <button
                            type="button"
                            onClick={() => remove(p)}
                            className="text-slate-400 hover:text-red-600"
                            aria-label={`${t("cal.delete")} ${p.name}`}
                          >
                            <Trash2 size={15} aria-hidden="true" />
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function AddPeriod({ apps, onAdded }: { apps: string[]; onAdded: () => void }) {
  const { t, label } = useI18n();
  const today = new Date().toISOString().slice(0, 10);
  const [name, setName] = useState("");
  const [periodType, setPeriodType] = useState<CalendarPeriodType>("MONTH_END_CLOSE");
  const [first, setFirst] = useState(today);
  const [last, setLast] = useState(today);
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (last < first) {
      setError(t("cal.badDates"));
      return;
    }
    setSaving(true);
    try {
      const end = new Date(`${last}T00:00:00Z`);
      end.setUTCDate(end.getUTCDate() + 1);
      await calendarApi.create({
        name,
        period_type: periodType,
        starts_at: `${first}T00:00:00Z`,
        ends_at: end.toISOString(),
        application_codes: codes,
      });
      setName("");
      setCodes([]);
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title={t("cal.add")}>
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-6">
        <div className="md:col-span-2">
          <Field label={t("cal.name")}>
            <input required minLength={3} maxLength={120} className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>
        <div className="md:col-span-2">
        <Field label={t("cal.type")}>
          <select className={inputClass} value={periodType} onChange={(e) => setPeriodType(e.target.value as CalendarPeriodType)}>
            {PERIOD_TYPES.map((pt) => (
              <option key={pt} value={pt}>
                {label(pt)}
              </option>
            ))}
          </select>
        </Field>
        </div>
        <div className="grid grid-cols-2 gap-2 md:col-span-2">
          <Field label={t("cal.first")}>
            <input type="date" required className={inputClass} value={first} onChange={(e) => setFirst(e.target.value)} />
          </Field>
          <Field label={t("cal.last")}>
            <input type="date" required className={inputClass} value={last} onChange={(e) => setLast(e.target.value)} />
          </Field>
        </div>
        <fieldset className="md:col-span-5">
          <legend className="mb-1 text-sm font-medium text-slate-700">{t("cal.applications")}</legend>
          <div className="flex flex-wrap gap-3 text-sm">
            {apps.map((code) => (
              <label key={code} className="inline-flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={codes.includes(code)}
                  onChange={(e) => setCodes(e.target.checked ? [...codes, code] : codes.filter((c) => c !== code))}
                />
                <span className="font-mono text-xs">{code}</span>
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-slate-500">{periodType === "BANK_HOLIDAY" ? t("cal.holidayHint") : t("cal.appsHint")}</p>
        </fieldset>
        <div className="flex items-end">
          <Button type="submit" disabled={saving}>
            <CalendarPlus size={15} aria-hidden="true" /> {t("cal.save")}
          </Button>
        </div>
        {error && (
          <div className="md:col-span-6">
            <ErrorBanner message={error} onClose={() => setError(null)} />
          </div>
        )}
      </form>
    </Card>
  );
}
