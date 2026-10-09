import React from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useApiConfig } from "../hooks/useApiConfig";
import { getHostHistory } from "../api/hosts";
import { BooleanBadge } from "../components/Badge";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { EmptyState } from "../components/EmptyState";
import { formatDateTime, formatDurationMs } from "../utils/format";
import { ArrowLeft, Server, History } from "lucide-react";

export const HostDetailPage: React.FC = () => {
  const { target } = useParams<{ target: string }>();
  const { client, pollInterval } = useApiConfig();

  const { data, isLoading, error } = useQuery({
    queryKey: ["host-history", target],
    queryFn: () => getHostHistory(client, target || ""),
    enabled: Boolean(target),
    refetchInterval: pollInterval > 0 ? pollInterval : false,
  });

  if (!target) {
    return (
      <EmptyState
        title="Invalid Host Target"
        message="A target host address must be specified."
        action={
          <Link to="/hosts" className="btn btn-primary btn-sm">
            Back to Hosts
          </Link>
        }
      />
    );
  }

  if (isLoading) {
    return <LoadingSpinner message={`Loading history for ${target}...`} />;
  }

  if (error || !data) {
    const errorMsg = error instanceof Error ? error.message : `Host '${target}' not found.`;
    return (
      <EmptyState
        title="Host Not Found"
        message={errorMsg}
        action={
          <Link to="/hosts" className="btn btn-primary btn-sm">
            Back to Hosts
          </Link>
        }
      />
    );
  }

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: "1.25rem" }}>
        <Link to="/hosts" className="btn btn-sm" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.75rem" }}>
          <ArrowLeft size={16} />
          <span>Back to Hosts</span>
        </Link>

        {/* Host Meta Card */}
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1rem" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <Server size={20} style={{ color: "var(--color-accent)" }} />
                <h2 style={{ fontSize: "1.25rem", fontWeight: 700 }}>{data.address}</h2>
                <BooleanBadge value={data.enabled} />
              </div>
              <div style={{ fontSize: "0.875rem", color: "var(--color-text-muted)", marginTop: "0.25rem" }}>
                {data.name ? `Label: ${data.name}` : "No custom label"} • Host ID #{data.host_id}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Scans History Section */}
      <div style={{ marginTop: "1.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <History size={18} style={{ color: "var(--color-accent)" }} />
          <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>Monitoring Scan History</h3>
        </div>

        {data.scans.length === 0 ? (
          <EmptyState
            title="No Scans Recorded"
            message={`No monitoring cycles have been executed for ${data.address} yet.`}
          />
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Scan ID</th>
                  <th>Status</th>
                  <th>Response Time</th>
                  <th>Started</th>
                  <th>Ports Probed</th>
                  <th>Events</th>
                  <th>Alerts</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {data.scans.map((scan) => (
                  <tr key={scan.scan_id}>
                    <td>#{scan.scan_id}</td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          backgroundColor:
                            scan.status.toUpperCase() === "AVAILABLE"
                              ? "var(--color-success-bg)"
                              : "var(--color-danger-bg)",
                          color:
                            scan.status.toUpperCase() === "AVAILABLE"
                              ? "var(--color-success)"
                              : "var(--color-danger)",
                          border: `1px solid ${
                            scan.status.toUpperCase() === "AVAILABLE"
                              ? "var(--color-success)"
                              : "var(--color-danger)"
                          }`,
                        }}
                      >
                        {scan.status.toUpperCase()}
                      </span>
                    </td>
                    <td>{formatDurationMs(scan.response_time_ms)}</td>
                    <td title={scan.started_at}>{formatDateTime(scan.started_at)}</td>
                    <td>{scan.port_count}</td>
                    <td>{scan.event_count}</td>
                    <td>
                      {scan.alert_count > 0 ? (
                        <span style={{ fontWeight: 700, color: "var(--color-danger)" }}>
                          {scan.alert_count}
                        </span>
                      ) : (
                        "0"
                      )}
                    </td>
                    <td>
                      <Link to={`/scans/${scan.scan_id}`} className="btn btn-sm">
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
