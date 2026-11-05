import { Loader2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { healthApi } from "../services/api";

/**
 * Free hosting puts the backend to sleep when idle; the first request can take about a minute.
 * Instead of showing errors, wait here and retry until the API answers, then render the app.
 */
export default function ServerGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [attempts, setAttempts] = useState(0);
  // Static pages (the architecture tab) need no backend - show them while the API wakes up
  const staticPage = useLocation().pathname.startsWith("/architecture");

  useEffect(() => {
    if (ready) return;
    let cancelled = false;
    healthApi
      .check()
      .then(() => !cancelled && setReady(true))
      .catch(() => {
        if (!cancelled) window.setTimeout(() => !cancelled && setAttempts((n) => n + 1), 4000);
      });
    return () => {
      cancelled = true;
    };
  }, [ready, attempts]);

  if (ready || staticPage) return <>{children}</>;
  return (
    <div className="mx-auto mt-16 max-w-md rounded-lg bg-white p-6 text-center shadow-sm ring-1 ring-slate-200">
      <Loader2 size={28} className="mx-auto animate-spin text-navy-800" aria-hidden="true" />
      <h1 className="mt-3 text-lg font-semibold text-navy-900">{attempts === 0 ? "Connecting…" : "Waking up the demo server…"}</h1>
      <p className="mt-2 text-sm text-slate-600">
        {attempts === 0
          ? "Checking the BankOps AI backend."
          : "The free hosting plan sleeps when idle. It usually wakes within a minute, with fresh demo data."}
      </p>
      {attempts > 0 && <p className="mt-3 text-xs text-slate-500">Attempt {attempts + 1}</p>}
    </div>
  );
}
