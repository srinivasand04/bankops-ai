import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import ServerGate from "./components/ServerGate";
import ArchitecturePage from "./pages/ArchitecturePage";
import DashboardPage from "./pages/DashboardPage";
import IncidentDetailPage from "./pages/IncidentDetailPage";
import IncidentsPage from "./pages/IncidentsPage";
import InvestigationDetailPage from "./pages/InvestigationDetailPage";
import InvestigationsPage from "./pages/InvestigationsPage";
import { getIdentity, setIdentity, type Identity } from "./services/identity";

export default function App() {
  const [identity, setIdentityState] = useState<Identity>(getIdentity());

  const changeIdentity = (next: Identity) => {
    setIdentity(next);
    setIdentityState(next);
  };

  return (
    <BrowserRouter>
      <Layout identity={identity} onIdentityChange={changeIdentity}>
        <ServerGate>
          {/* key: remount pages when the user changes so data and permissions refresh */}
          <Routes key={identity.name}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/incidents/:id" element={<IncidentDetailPage identity={identity} />} />
            <Route path="/investigations" element={<InvestigationsPage identity={identity} />} />
            <Route path="/investigations/:id" element={<InvestigationDetailPage identity={identity} />} />
            <Route path="/architecture" element={<ArchitecturePage />} />
          </Routes>
        </ServerGate>
      </Layout>
    </BrowserRouter>
  );
}
