import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { en, type MessageKey } from "./en";
import { fr } from "./fr";

export type Lang = "en" | "fr";
const DICTS: Record<Lang, Record<MessageKey, string>> = { en, fr };
const LOCALES: Record<Lang, string> = { en: "en-GB", fr: "fr-FR" };
const STORAGE_KEY = "bankops.lang";

// Plain helpers (formatTime, timeAgo…) read the active language from here; the provider keeps it current.
let active: Lang = initialLang();

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "fr") return saved;
  } catch {
    // storage unavailable - fall back to the browser language
  }
  return typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("fr") ? "fr" : "en";
}

export function translate(key: MessageKey, vars?: Record<string, string | number>, lang: Lang = active): string {
  let text = DICTS[lang][key] ?? en[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) text = text.replaceAll(`{${k}}`, String(v));
  return text;
}

/** Label for a backend enum value (status, category, event type…); unknown values fall back to "SOME VALUE". */
export function enumLabel(value: string, lang: Lang = active): string {
  const key = `enum.${value}` as MessageKey;
  return key in en ? translate(key, undefined, lang) : value.replaceAll("_", " ");
}

export function currentLocale(): string {
  return LOCALES[active];
}

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
  label: (value: string) => string;
}

const Ctx = createContext<I18n | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(active);
  active = lang;

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    active = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // not persisted in private mode - still switches for this visit
    }
    setLangState(next);
  }, []);

  const value = useMemo<I18n>(
    () => ({ lang, setLang, t: (key, vars) => translate(key, vars, lang), label: (v) => enumLabel(v, lang) }),
    [lang, setLang],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n must be used inside <LanguageProvider>");
  return ctx;
}

/** EN / FR switch for the header. */
export function LanguageToggle() {
  const { lang, setLang, t } = useI18n();
  return (
    <div role="group" aria-label={t("header.language")} className="inline-flex overflow-hidden rounded-md ring-1 ring-slate-300">
      {(["en", "fr"] as Lang[]).map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => setLang(l)}
          aria-pressed={lang === l}
          className={`px-2.5 py-1 text-xs font-semibold ${lang === l ? "bg-navy-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
