import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useApiConfig } from "../hooks/useApiConfig";
import { getHealthLive, getHealthReady } from "../api/health";
import { Activity, Database, Server } from "lucide-react";

export const HealthIndicator: React.FC = () => {
  const { client, pollInterval } = useApiConfig();

  const { data: liveData, isError: liveError } = useQuery({
    queryKey: ["health-live"],
    queryFn: () => getHealthLive(client),
    refetchInterval: pollInterval > 0 ? pollInterval : false,
    retry: 1,
  });

  const { data: readyData, isError: readyError } = useQuery({
    queryKey: ["health-ready"],
    queryFn: () => getHealthReady(client),
    refetchInterval: pollInterval > 0 ? pollInterval : false,
    retry: 1,
  });

  const apiOnline = Boolean(liveData && !liveError && liveData.status === "ok");
  const dbReady = Boolean(
    readyData && !readyError &&
    readyData.status === "ready" && readyData.database === "available"
  );

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.875rem",
        fontSize: "0.75rem",
        padding: "0.35rem 0.75rem",
        borderRadius: "var(--radius-sm)",
        backgroundColor: "var(--color-surface-hover)",
        border: "1px solid var(--color-border)",
      }}
      aria-label="System Health Status"
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}>
        <Server size={14} style={{ color: "var(--color-text-muted)" }} />
        <span>API:</span>
        <span
          style={{
            fontWeight: 600,
            color: apiOnline ? "var(--color-success)" : "var(--color-danger)",
          }}
        >
          {apiOnline ? "Online" : "Unavailable"}
        </span>
      </div>

      <div style={{ width: "1px", height: "12px", backgroundColor: "var(--color-border)" }} />

      <div style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}>
        <Database size={14} style={{ color: "var(--color-text-muted)" }} />
        <span>DB:</span>
        <span
          style={{
            fontWeight: 600,
            color: dbReady ? "var(--color-success)" : "var(--color-danger)",
          }}
        >
          {dbReady ? "Ready" : "Unavailable"}
        </span>
      </div>

      <Activity
        size={14}
        style={{
          color: apiOnline && dbReady ? "var(--color-success)" : "var(--color-danger)",
        }}
      />
    </div>
  );
};
