import React from "react";
import { Routes, Route } from "react-router-dom";
import { Layout } from "./layouts/Layout";
import { OverviewPage } from "./pages/OverviewPage";
import { AlertsPage } from "./pages/AlertsPage";
import { AlertDetailPage } from "./pages/AlertDetailPage";
import { HostsPage } from "./pages/HostsPage";
import { HostDetailPage } from "./pages/HostDetailPage";
import { ScansPage } from "./pages/ScansPage";
import { ScanDetailPage } from "./pages/ScanDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ErrorBoundary } from "./components/ErrorBoundary";

export const App: React.FC = () => {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="alerts/:alertId" element={<AlertDetailPage />} />
          <Route path="hosts" element={<HostsPage />} />
          <Route path="hosts/:target" element={<HostDetailPage />} />
          <Route path="scans" element={<ScansPage />} />
          <Route path="scans/:scanId" element={<ScanDetailPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
};
