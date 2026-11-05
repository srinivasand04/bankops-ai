import { ExternalLink } from "lucide-react";

// The architecture one-pager is a static page (frontend/public/architecture.html) so the same file can be
// shared on its own. Shown here inside the app layout; it needs no backend.
export default function ArchitecturePage() {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold text-navy-900">Architecture and deployment</h1>
        <a
          href="/architecture.html"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50"
        >
          <ExternalLink size={14} aria-hidden="true" /> Open full page
        </a>
      </div>
      <iframe
        title="BankOps AI architecture"
        src="/architecture.html"
        className="h-[calc(100vh-11rem)] min-h-[600px] w-full rounded-lg bg-white ring-1 ring-slate-200"
      />
    </div>
  );
}
