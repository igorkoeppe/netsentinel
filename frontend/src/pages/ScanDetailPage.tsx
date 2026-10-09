import React from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useApiConfig } from "../hooks/useApiConfig";
import { getScan } from "../api/scans";
import { SeverityBadge } from "../components/Badge";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { EmptyState } from "../components/EmptyState";
import { formatDateTime, formatDurationMs } from "../utils/format";
import {
  ArrowLeft,
  Radar,
  Network,
  Activity,
  AlertTriangle,
  ExternalLink,
} from "lucide-react";

export const ScanDetailPage: React.FC = () => {
  const { scanId } = useParams<{ scanId: string }>();
  const idNumber = parseInt(scanId || "0", 10);
  const { client, pollInterval } = useApiConfig();

  const { data: scan, isLoading, error } = useQuery({
    queryKey: ["scan", idNumber],
    queryFn: () => getScan(client, idNumber),
    enabled: idNumber > 0,
    refetchInterval: pollInterval > 0 ? pollInterval : false,
  });

  if (idNumber <= 0) {
    return (
      <EmptyState
        title="Invalid Scan ID"
        message="The scan ID must be a positive integer."
        action={
          <Link to="/scans" className="btn btn-primary btn-sm">
            Back to Scans
          </Link>
        }
      />
    );
  }

  if (isLoading) {
    return <LoadingSpinner message={`Loading details for scan #${idNumber}...`} />;
  }

  if (error || !scan) {
    const errorMsg = error instanceof Error ? error.message : `Scan #${idNumber} not found.`;
    return (
      <EmptyState
        title="Scan Not Found"
        message={errorMsg}
        action={
          <Link to="/scans" className="btn btn-primary btn-sm">
            Back to Scans
          </Link>
        }
      />
    );
  }

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: "1.25rem" }}>
        <Link to="/scans" className="btn btn-sm" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.75rem" }}>
          <ArrowLeft size={16} />
          <span>Back to Scans</span>
        </Link>

        {/* Scan Overview Card */}
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
            <Radar size={22} style={{ color: "var(--color-accent)" }} />
            <h2 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Scan #{scan.id}</h2>
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
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "1.25rem",
              fontSize: "0.875rem",
            }}
          >
            <div>
              <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
                Target Host
              </div>
              <div style={{ fontWeight: 600, marginTop: "0.25rem" }}>
                {scan.target ? (
                  <Link
                    to={`/hosts/${encodeURIComponent(scan.target)}`}
                    style={{ color: "var(--color-accent)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: "0.25rem" }}
                  >
                    <span>{scan.target}</span>
                    <ExternalLink size={12} />
                  </Link>
                ) : (
                  "—"
                )}
              </div>
            </div>

            <div>
              <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
                Response Time
              </div>
              <div style={{ fontWeight: 600, marginTop: "0.25rem" }}>
                {formatDurationMs(scan.response_time_ms)}
              </div>
            </div>

            <div>
              <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
                Started At
              </div>
              <div style={{ marginTop: "0.25rem" }} title={scan.started_at}>
                {formatDateTime(scan.started_at)}
              </div>
            </div>

            <div>
              <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
                Finished At
              </div>
              <div style={{ marginTop: "0.25rem" }} title={scan.finished_at || undefined}>
                {formatDateTime(scan.finished_at)}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Ports Section */}
      <div style={{ marginBottom: "2rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <Network size={18} style={{ color: "var(--color-accent)" }} />
          <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>Probed Ports</h3>
        </div>

        {scan.ports.length === 0 ? (
          <EmptyState message="No port probe results recorded for this scan." />
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Port</th>
                  <th>Status</th>
                  <th>Response Time</th>
                </tr>
              </thead>
              <tbody>
                {scan.ports.map((port) => (
                  <tr key={port.port}>
                    <td>
                      <code style={{ fontSize: "0.875rem", fontWeight: 700 }}>
                        {port.port}
                      </code>
                    </td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          backgroundColor:
                            port.status === "OPEN"
                              ? "var(--color-success-bg)"
                              : "var(--color-surface-hover)",
                          color:
                            port.status === "OPEN"
                              ? "var(--color-success)"
                              : "var(--color-text-muted)",
                          border: `1px solid ${
                            port.status === "OPEN"
                              ? "var(--color-success)"
                              : "var(--color-border)"
                          }`,
                        }}
                      >
                        {port.status}
                      </span>
                    </td>
                    <td>{formatDurationMs(port.response_time_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Monitoring Events Section */}
      <div style={{ marginBottom: "2rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <Activity size={18} style={{ color: "var(--color-accent)" }} />
          <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>Observed Monitoring Events</h3>
        </div>

        {scan.events.length === 0 ? (
          <EmptyState message="No state change events detected during this scan." />
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Event Type</th>
                  <th>Port</th>
                  <th>Transition</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {scan.events.map((evt, idx) => (
                  <tr key={idx}>
                    <td>
                      <code>{evt.event_type}</code>
                    </td>
                    <td>{evt.port !== null ? evt.port : "—"}</td>
                    <td>
                      {evt.previous_state || "—"} → {evt.current_state || "—"}
                    </td>
                    <td title={evt.created_at}>{formatDateTime(evt.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Security Alerts Section */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <AlertTriangle size={18} style={{ color: "var(--color-high)" }} />
          <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>Generated Security Alerts</h3>
        </div>

        {scan.alerts.length === 0 ? (
          <EmptyState message="No security alerts generated by this scan cycle." />
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Severity</th>
                  <th>Rule Type</th>
                  <th>Message</th>
                  <th>Port</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {scan.alerts.map((al) => (
                  <tr key={al.id}>
                    <td>#{al.id}</td>
                    <td>
                      <SeverityBadge severity={al.severity} />
                    </td>
                    <td>
                      <code>{al.alert_type}</code>
                    </td>
                    <td>{al.message}</td>
                    <td>{al.port !== null ? al.port : "—"}</td>
                    <td>
                      <Link to={`/alerts/${al.id}`} className="btn btn-sm">
                        View Alert
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
