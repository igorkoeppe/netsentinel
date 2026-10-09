import React from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useApiConfig } from "../hooks/useApiConfig";
import { getDashboardSummary } from "../api/dashboard";
import { listAlerts } from "../api/alerts";
import { listScans } from "../api/scans";
import { Card } from "../components/Card";
import { StatusChart, SeverityChart } from "../components/Charts";
import { SeverityBadge, StatusBadge } from "../components/Badge";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { EmptyState } from "../components/EmptyState";
import { formatDateTime, formatDurationMs, formatPort } from "../utils/format";
import {
  Server,
  AlertTriangle,
  CheckCircle,
  Clock,
  ShieldAlert,
  Radar,
  ArrowRight,
} from "lucide-react";

export const OverviewPage: React.FC = () => {
  const { client, pollInterval } = useApiConfig();

  const {
    data: summary,
    isLoading: summaryLoading,
    error: summaryError,
  } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => getDashboardSummary(client),
    refetchInterval: pollInterval > 0 ? pollInterval : false,
  });

  const {
    data: recentAlertsData,
    isLoading: alertsLoading,
  } = useQuery({
    queryKey: ["recent-alerts"],
    queryFn: () => listAlerts(client, { limit: 5, offset: 0 }),
    refetchInterval: pollInterval > 0 ? pollInterval : false,
  });

  const {
    data: recentScansData,
    isLoading: scansLoading,
  } = useQuery({
    queryKey: ["recent-scans"],
    queryFn: () => listScans(client, { limit: 5, offset: 0 }),
    refetchInterval: pollInterval > 0 ? pollInterval : false,
  });

  if (summaryLoading) {
    return <LoadingSpinner message="Loading operational metrics..." />;
  }

  if (summaryError) {
    const errorMsg = summaryError instanceof Error ? summaryError.message : "Failed to load dashboard summary.";
    return (
      <div>
        <EmptyState
          title="Overview Unavailable"
          message={errorMsg}
          action={
            <Link to="/settings" className="btn btn-primary btn-sm">
              Open Connection Settings
            </Link>
          }
        />
      </div>
    );
  }

  const hostsTotal = summary?.hosts.total ?? 0;
  const hostsActive = summary?.hosts.enabled ?? 0;
  const openAlerts = summary?.alerts.by_status["OPEN"] ?? 0;
  const ackAlerts = summary?.alerts.by_status["ACKNOWLEDGED"] ?? 0;
  const resolvedAlerts = summary?.alerts.by_status["RESOLVED"] ?? 0;
  const highCriticalAlerts =
    (summary?.alerts.by_severity["HIGH"] ?? 0) +
    (summary?.alerts.by_severity["CRITICAL"] ?? 0);
  const scansTotal = summary?.scans.total ?? 0;
  const lastScanAt = summary?.scans.last_scan_at;

  const recentAlerts = recentAlertsData?.items || [];
  const recentScans = recentScansData?.items || [];

  return (
    <div>
      {/* Metrics Row */}
      <div className="grid-cards">
        <Card
          title="Monitored Hosts"
          value={hostsTotal}
          subtitle={`${hostsActive} active`}
          icon={<Server size={22} />}
          accentColor="var(--color-accent)"
        />
        <Card
          title="Open Alerts"
          value={openAlerts}
          subtitle="Requires attention"
          icon={<AlertTriangle size={22} />}
          accentColor="var(--color-danger)"
        />
        <Card
          title="Acknowledged"
          value={ackAlerts}
          subtitle="In triage"
          icon={<Clock size={22} />}
          accentColor="var(--color-warning)"
        />
        <Card
          title="Resolved Alerts"
          value={resolvedAlerts}
          subtitle="Triaged successfully"
          icon={<CheckCircle size={22} />}
          accentColor="var(--color-success)"
        />
        <Card
          title="High / Critical"
          value={highCriticalAlerts}
          subtitle="Elevated severity"
          icon={<ShieldAlert size={22} />}
          accentColor="var(--color-critical)"
        />
        <Card
          title="Total Scans"
          value={scansTotal}
          subtitle={lastScanAt ? `Last: ${formatDateTime(lastScanAt)}` : "No scans yet"}
          icon={<Radar size={22} />}
          accentColor="var(--color-info)"
        />
      </div>

      {/* Visualizations Row */}
      {summary && (
        <div className="grid-two-cols">
          <StatusChart data={summary.alerts.by_status} />
          <SeverityChart data={summary.alerts.by_severity} />
        </div>
      )}

      {/* Recent Alerts Section */}
      <div style={{ marginBottom: "2rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
          <h2 style={{ fontSize: "1rem", fontWeight: 700 }}>Recent Security Alerts</h2>
          <Link to="/alerts" className="btn btn-sm" style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
            <span>View all alerts</span>
            <ArrowRight size={14} />
          </Link>
        </div>

        {alertsLoading ? (
          <LoadingSpinner size={20} />
        ) : recentAlerts.length === 0 ? (
          <EmptyState message="No security alerts recorded." />
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Type</th>
                  <th>Target</th>
                  <th>Port</th>
                  <th>Created</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {recentAlerts.map((alert) => (
                  <tr key={alert.id}>
                    <td>
                      <SeverityBadge severity={alert.severity} />
                    </td>
                    <td>
                      <StatusBadge status={alert.status} />
                    </td>
                    <td>
                      <code style={{ fontSize: "0.8125rem", color: "var(--color-text)" }}>
                        {alert.alert_type}
                      </code>
                    </td>
                    <td>{alert.target}</td>
                    <td>{formatPort(alert.port)}</td>
                    <td title={alert.created_at}>{formatDateTime(alert.created_at)}</td>
                    <td>
                      <Link to={`/alerts/${alert.id}`} className="btn btn-sm">
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent Scans Section */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
          <h2 style={{ fontSize: "1rem", fontWeight: 700 }}>Recent Monitoring Scans</h2>
          <Link to="/scans" className="btn btn-sm" style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
            <span>View all scans</span>
            <ArrowRight size={14} />
          </Link>
        </div>

        {scansLoading ? (
          <LoadingSpinner size={20} />
        ) : recentScans.length === 0 ? (
          <EmptyState message="No monitoring scans recorded." />
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Target</th>
                  <th>Status</th>
                  <th>Response Time</th>
                  <th>Started</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {recentScans.map((scan) => (
                  <tr key={scan.id}>
                    <td>#{scan.id}</td>
                    <td>{scan.target}</td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          backgroundColor:
                            scan.status === "AVAILABLE"
                              ? "var(--color-success-bg)"
                              : "var(--color-danger-bg)",
                          color:
                            scan.status === "AVAILABLE"
                              ? "var(--color-success)"
                              : "var(--color-danger)",
                          border: `1px solid ${
                            scan.status === "AVAILABLE"
                              ? "var(--color-success)"
                              : "var(--color-danger)"
                          }`,
                        }}
                      >
                        {scan.status}
                      </span>
                    </td>
                    <td>{formatDurationMs(scan.response_time_ms)}</td>
                    <td title={scan.started_at}>{formatDateTime(scan.started_at)}</td>
                    <td>
                      <Link to={`/scans/${scan.id}`} className="btn btn-sm">
                        Details
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
