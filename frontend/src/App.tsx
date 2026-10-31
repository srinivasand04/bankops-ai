import { Landmark } from "lucide-react";

import DashboardPage from "./pages/DashboardPage";

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="bg-navy-950 text-white">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3">
          <Landmark size={22} />
          <div>
            <div className="font-semibold">BankOps AI</div>
            <div className="text-xs text-slate-300">Banking Operational Risk &amp; IT Incident Intelligence</div>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <DashboardPage />
      </main>
    </div>
  );
}
