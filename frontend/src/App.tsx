import { lazy, Suspense, useCallback, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import ServerGate from "./components/ServerGate";
import ArchitecturePage from "./pages/ArchitecturePage";
import CalendarPage from "./pages/CalendarPage";
import DashboardPage from "./pages/DashboardPage";
import IncidentDetailPage from "./pages/IncidentDetailPage";
import IncidentsPage from "./pages/IncidentsPage";
import InvestigationDetailPage from "./pages/InvestigationDetailPage";
import InvestigationsPage from "./pages/InvestigationsPage";
import UsersPage from "./pages/UsersPage";
// Charts library is large - load the reports page only when it is opened
const ReportsPage = lazy(() => import("./pages/ReportsPage"));
const MlLabPage = lazy(() => import("./pages/MlLabPage"));
import { getIdentity, setIdentity, type Identity } from "./services/identity";

export default function App() {
  const [identity, setIdentityState] = useState<Identity>(getIdentity());

  const [usersVersion, setUsersVersion] = useState(0);

  const changeIdentity = useCallback((next: Identity) => {
    setIdentity(next);
    setIdentityState(next);
  }, []);

  return (
    <BrowserRouter>
      <Layout identity={identity} onIdentityChange={changeIdentity} usersVersion={usersVersion}>
        <ServerGate>
          {/* key: remount pages when the user changes so data and permissions refresh */}
          <Routes key={`${identity.name}-${identity.role}`}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/incidents/:id" element={<IncidentDetailPage identity={identity} />} />
            <Route path="/investigations" element={<InvestigationsPage identity={identity} />} />
            <Route path="/investigations/:id" element={<InvestigationDetailPage identity={identity} />} />
            <Route path="/calendar" element={<CalendarPage identity={identity} />} />
            <Route path="/reports" element={<Suspense fallback={null}><ReportsPage /></Suspense>} />
            <Route path="/ml" element={<Suspense fallback={null}><MlLabPage identity={identity} /></Suspense>} />
            <Route path="/users" element={<UsersPage identity={identity} onUsersChanged={() => setUsersVersion((v) => v + 1)} />} />
            <Route path="/architecture" element={<ArchitecturePage />} />
          </Routes>
        </ServerGate>
      </Layout>
    </BrowserRouter>
  );
}
