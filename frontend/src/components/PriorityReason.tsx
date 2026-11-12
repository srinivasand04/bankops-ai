import { CalendarClock } from "lucide-react";
import { Link } from "react-router-dom";

import { enumLabel, useI18n, type Lang } from "../i18n";

// The backend writes the reason in English; these rules give the French version of its fixed phrases.
const FR_RULES: [RegExp, string][] = [
  [/(P\d) base priority (\w+)/g, "$1 : priorité de base $2"],
  [/Tier (\d) application ([+-]1)/g, "Application Tier $1 $2"],
  [/Business calendar \(/g, "Calendrier métier ("],
  [/already (\w+) \(highest\)/g, "déjà $1 (maximum)"],
  [/Context only, no change:/g, "Contexte seulement, sans effet :"],
  [/Set manually by ([^\s:(]+)/g, "Définie manuellement par $1"],
  [/\(calculated: (\w+)\)/g, "(calculée : $1)"],
  [/Provided by source/g, "Fournie par la source"],
  [/, day (\d+)/g, ", jour $1"],
  ...periodNameRulesFr(),
];

export function periodNameRulesFr(): [RegExp, string][] {
  const months: Record<string, string> = {
    Jan: "janv.", Feb: "févr.", Mar: "mars", Apr: "avr.", May: "mai", Jun: "juin",
    Jul: "juil.", Aug: "août", Sep: "sept.", Oct: "oct.", Nov: "nov.", Dec: "déc.",
  };
  const holidays: Record<string, string> = {
    "New Year's Day": "Jour de l'An", "Easter Monday": "Lundi de Pâques", "Labour Day": "Fête du Travail",
    "Victory in Europe Day": "Victoire 1945", "Ascension Day": "Ascension", "Whit Monday": "Lundi de Pentecôte",
    "Bastille Day": "Fête nationale", "Assumption Day": "Assomption", "All Saints' Day": "Toussaint",
    "Armistice Day": "Armistice", "Christmas Day": "Noël", "Good Friday": "Vendredi saint",
    "St Stephen's Day": "Saint-Étienne",
  };
  const descriptions: Record<string, string> = {
    "Annual accounts closing: ledger, reconciliations and statutory reporting":
      "Clôture des comptes annuels : grand livre, rapprochements et reporting réglementaire",
    "Quarterly closing: ledger, liquidity and capital figures": "Clôture trimestrielle : grand livre, liquidité et fonds propres",
    "Monthly closing: last working day to the 3rd working day of the next month":
      "Clôture mensuelle : du dernier jour ouvré au 3e jour ouvré du mois suivant",
    "Salary credits to customers: payment volumes peak around the 25th":
      "Versement des salaires aux clients : pic des paiements autour du 25",
    "Supervisory reporting to the regulator; remittance date from the EBA reporting calendar":
      "Reporting prudentiel au superviseur ; date de remise du calendrier de reporting de l'ABE",
    "Card and online payment volumes peak": "Pic des paiements par carte et en ligne",
    "French public holiday: reduced support staffing, branches closed": "Jour férié en France : support réduit, agences fermées",
    "Euro large-value payment system closed: payments wait for the next business day":
      "Système de paiement de gros montants en euros fermé : les paiements attendent le jour ouvré suivant",
  };
  const literal = (text: string) => new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
  return [
    ...Object.entries(descriptions).map(([en, fr]) => [literal(en), fr] as [RegExp, string]),
    [/Year-end close/g, "Clôture annuelle"],
    [/Quarter-end close/g, "Clôture trimestrielle"],
    [/Month-end close/g, "Clôture mensuelle"],
    [/Salary payment run/g, "Paiement des salaires"],
    [/COREP\/FINREP submission/g, "Remise COREP/FINREP"],
    [/Black Friday to Cyber Monday/g, "Du Black Friday au Cyber Monday"],
    [/Bank holiday:/g, "Jour férié :"],
    [/TARGET2 closed:/g, "TARGET2 fermé :"],
    [/\(demonstration calendar\)/g, "(calendrier de démonstration)"],
    ...Object.entries(holidays).map(([en, fr]) => [literal(en), fr] as [RegExp, string]),
    ...Object.entries(months).map(([en, fr]) => [new RegExp(`\\b${en} (\\d{4})\\b`, "g"), `${fr} $1`] as [RegExp, string]),
  ];
}

const FR_NAME_RULES = periodNameRulesFr();

function apply(text: string, rules: [RegExp, string][]): string {
  return rules.reduce((acc, [re, to]) => acc.replace(re, to), text);
}

/** Priority reason in the active language (backend text is English). */
export function translateReason(text: string, lang: Lang): string {
  if (lang !== "fr") return text;
  return apply(text, FR_RULES).replace(/\b(CRITICAL|HIGH|MEDIUM|LOW)\b/g, (p) => enumLabel(p, "fr"));
}

/** Calendar period name or description in the active language. */
export function translatePeriodText(text: string, lang: Lang): string {
  return lang === "fr" ? apply(text, FR_NAME_RULES) : text;
}

/** One line under the incident header: why it has this priority, step by step. */
export default function PriorityReason({ reason }: { reason: string | null }) {
  const { t, lang } = useI18n();
  if (!reason) return null;
  const calendar = reason.includes("Business calendar") || reason.includes("Context only");
  return (
    <p className="mt-2 flex flex-wrap items-start gap-1.5 text-sm text-slate-600" data-testid="priority-reason">
      {calendar && <CalendarClock size={15} className="mt-0.5 shrink-0 text-amber-600" aria-hidden="true" />}
      <b className="font-medium text-slate-700">{t("prio.reason")}</b>
      <span>{translateReason(reason, lang)}</span>
      {calendar && <Link to="/calendar" className="text-navy-800 underline hover:text-navy-950">{t("prio.seeCalendar")}</Link>}
    </p>
  );
}
