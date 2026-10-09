import React, { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiConfig } from "../hooks/useApiConfig";
import { listAlerts, acknowledgeAlert, resolveAlert } from "../api/alerts";
import { AlertSeverity, AlertStatus } from "../api/types";
import { SeverityBadge, StatusBadge } from "../components/Badge";
import { Pagination } from "../components/Pagination";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { EmptyState } from "../components/EmptyState";
import { Toast, ToastType } from "../components/Toast";
import { ConfirmModal } from "../components/ConfirmModal";
import { formatDateTime, formatPort } from "../utils/format";
import { Filter, X, CheckCircle, Clock } from "lucide-react";

export const AlertsPage: React.FC = () => {
  const { client, pollInterval } = useApiConfig();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  // URL state synchronization
  const statusParam = (searchParams.get("status") as AlertStatus) || undefined;
  const severityParam = (searchParams.get("severity") as AlertSeverity) || undefined;
  const typeParam = searchParams.get("type") || undefined;
  const targetParam = searchParams.get("target") || undefined;
  const limitParam = parseInt(searchParams.get("limit") || "20", 10);
  const offsetParam = parseInt(searchParams.get("offset") || "0", 10);

  // Local form state for inputs
  const [targetInput, setTargetInput] = useState(targetParam || "");
  const [typeInput, setTypeInput] = useState(typeParam || "");

  // Feedback toast state
  const [toast, setToast] = useState<{ type: ToastType; message: string } | null>(null);

  // Confirmation modal state
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    action: () => void;
  }>({
    isOpen: false,
    title: "",
    message: "",
    action: () => {},
  });

  const queryKey = [
    "alerts",
    {
      status: statusParam,
      severity: severityParam,
      type: typeParam,
      target: targetParam,
      limit: limitParam,
      offset: offsetParam,
    },
  ];

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () =>
      listAlerts(client, {
        status: statusParam,
        severity: severityParam,
        type: typeParam,
        target: targetParam,
        limit: limitParam,
        offset: offsetParam,
      }),
    refetchInterval: pollInterval > 0 ? pollInterval : false,
  });

  const updateParam = (key: string, value: string | undefined) => {
    const next = new URLSearchParams(searchParams);
    if (value && value.trim()) {
      next.set(key, value.trim());
    } else {
      next.delete(key);
    }
    // Reset offset on filter changes
    if (key !== "offset" && key !== "limit") {
      next.delete("offset");
    }
    setSearchParams(next);
  };

  const handleClearFilters = () => {
    setTargetInput("");
    setTypeInput("");
    setSearchParams({});
  };

  const ackMutation = useMutation({
    mutationFn: (alertId: number) => acknowledgeAlert(client, alertId),
    onSuccess: (updatedAlert) => {
      setToast({
        type: "success",
        message: `Alert #${updatedAlert.id} acknowledged successfully.`,
      });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      setConfirmModal((prev) => ({ ...prev, isOpen: false }));
    },
    onError: (err: unknown) => {
      setConfirmModal((prev) => ({ ...prev, isOpen: false }));
      const status = (err as { status?: number }).status;
      const code = (err as { code?: string }).code;

      if (status === 409 || code === "INVALID_TRANSITION") {
        setToast({
          type: "warning",
          message: "Alert state changed. Refreshing data.",
        });
        queryClient.invalidateQueries({ queryKey: ["alerts"] });
      } else {
        const msg = err instanceof Error ? err.message : "Failed to acknowledge alert.";
        setToast({ type: "error", message: msg });
      }
    },
  });

  const resolveMutation = useMutation({
    mutationFn: (alertId: number) => resolveAlert(client, alertId),
    onSuccess: (updatedAlert) => {
      setToast({
        type: "success",
        message: `Alert #${updatedAlert.id} resolved successfully.`,
      });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      setConfirmModal((prev) => ({ ...prev, isOpen: false }));
    },
    onError: (err: unknown) => {
      setConfirmModal((prev) => ({ ...prev, isOpen: false }));
      const status = (err as { status?: number }).status;
      const code = (err as { code?: string }).code;

      if (status === 409 || code === "INVALID_TRANSITION") {
        setToast({
          type: "warning",
          message: "Alert state changed. Refreshing data.",
        });
        queryClient.invalidateQueries({ queryKey: ["alerts"] });
      } else {
        const msg = err instanceof Error ? err.message : "Failed to resolve alert.";
        setToast({ type: "error", message: msg });
      }
    },
  });

  const handleAcknowledgeClick = (alertId: number) => {
    setConfirmModal({
      isOpen: true,
      title: `Acknowledge Alert #${alertId}`,
      message: `Are you sure you want to acknowledge alert #${alertId}? This marks it as actively triaged.`,
      action: () => ackMutation.mutate(alertId),
    });
  };

  const handleResolveClick = (alertId: number) => {
    setConfirmModal({
      isOpen: true,
      title: `Resolve Alert #${alertId}`,
      message: `Are you sure you want to resolve alert #${alertId}? This will mark it as closed/resolved.`,
      action: () => resolveMutation.mutate(alertId),
    });
  };

  const alerts = data?.items || [];
  const hasActiveFilters = Boolean(
    statusParam || severityParam || typeParam || targetParam
  );

  return (
    <div>
      {/* Toast Feedback */}
      {toast && (
        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() => setToast(null)}
        />
      )}

      {/* Filter Bar */}
      <div
        className="card"
        style={{
          marginBottom: "1.25rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.75rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.875rem", fontWeight: 600 }}>
          <Filter size={16} />
          <span>Filters</span>
          {hasActiveFilters && (
            <button
              onClick={handleClearFilters}
              className="btn btn-sm"
              style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: "0.25rem" }}
            >
              <X size={14} />
              <span>Clear filters</span>
            </button>
          )}
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: "0.75rem",
          }}
        >
          {/* Status Filter */}
          <div>
            <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: "0.25rem" }}>
              Status
            </label>
            <select
              value={statusParam || ""}
              onChange={(e) => updateParam("status", e.target.value || undefined)}
              aria-label="Filter by status"
            >
              <option value="">All Statuses</option>
              <option value="OPEN">OPEN</option>
              <option value="ACKNOWLEDGED">ACKNOWLEDGED</option>
              <option value="RESOLVED">RESOLVED</option>
            </select>
          </div>

          {/* Severity Filter */}
          <div>
            <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: "0.25rem" }}>
              Severity
            </label>
            <select
              value={severityParam || ""}
              onChange={(e) => updateParam("severity", e.target.value || undefined)}
              aria-label="Filter by severity"
            >
              <option value="">All Severities</option>
              <option value="INFO">INFO</option>
              <option value="LOW">LOW</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="HIGH">HIGH</option>
              <option value="CRITICAL">CRITICAL</option>
            </select>
          </div>

          {/* Target Filter */}
          <div>
            <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: "0.25rem" }}>
              Target Host
            </label>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                updateParam("target", targetInput || undefined);
              }}
            >
              <input
                type="text"
                className="input"
                placeholder="e.g. 192.168.1.1"
                value={targetInput}
                onChange={(e) => setTargetInput(e.target.value)}
                onBlur={() => updateParam("target", targetInput || undefined)}
                aria-label="Filter by target"
              />
            </form>
          </div>

          {/* Alert Type Filter */}
          <div>
            <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: "0.25rem" }}>
              Alert Type
            </label>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                updateParam("type", typeInput || undefined);
              }}
            >
              <input
                type="text"
                className="input"
                placeholder="e.g. UNEXPECTED_OPEN_PORT"
                value={typeInput}
                onChange={(e) => setTypeInput(e.target.value)}
                onBlur={() => updateParam("type", typeInput || undefined)}
                aria-label="Filter by alert type"
              />
            </form>
          </div>
        </div>
      </div>

      {/* Table Section */}
      {isLoading ? (
        <LoadingSpinner message="Loading security alerts..." />
      ) : error ? (
        <EmptyState
          title="Error Loading Alerts"
          message={error instanceof Error ? error.message : "Failed to load alerts."}
        />
      ) : alerts.length === 0 ? (
        <EmptyState
          title="No alerts found"
          message="No alerts match the current filters."
          action={
            hasActiveFilters ? (
              <button onClick={handleClearFilters} className="btn btn-sm">
                Clear all filters
              </button>
            ) : undefined
          }
        />
      ) : (
        <>
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
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td>
                      <SeverityBadge severity={alert.severity} />
                    </td>
                    <td>
                      <StatusBadge status={alert.status} />
                    </td>
                    <td>
                      <code style={{ fontSize: "0.8125rem" }}>{alert.alert_type}</code>
                    </td>
                    <td>{alert.target}</td>
                    <td>{formatPort(alert.port)}</td>
                    <td title={alert.created_at}>{formatDateTime(alert.created_at)}</td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                        <Link to={`/alerts/${alert.id}`} className="btn btn-sm">
                          Details
                        </Link>

                        {alert.status === "OPEN" && (
                          <button
                            className="btn btn-sm"
                            style={{ color: "var(--color-warning)" }}
                            onClick={() => handleAcknowledgeClick(alert.id)}
                            title="Acknowledge alert"
                            aria-label={`Acknowledge alert #${alert.id}`}
                          >
                            <Clock size={14} />
                            <span>Ack</span>
                          </button>
                        )}

                        {(alert.status === "OPEN" || alert.status === "ACKNOWLEDGED") && (
                          <button
                            className="btn btn-sm"
                            style={{ color: "var(--color-success)" }}
                            onClick={() => handleResolveClick(alert.id)}
                            title="Resolve alert"
                            aria-label={`Resolve alert #${alert.id}`}
                          >
                            <CheckCircle size={14} />
                            <span>Resolve</span>
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            offset={offsetParam}
            limit={limitParam}
            count={alerts.length}
            onPageChange={(newOffset) => updateParam("offset", String(newOffset))}
            onLimitChange={(newLimit) => updateParam("limit", String(newLimit))}
            isLoading={isLoading}
          />
        </>
      )}

      {/* Confirmation Dialog */}
      <ConfirmModal
        isOpen={confirmModal.isOpen}
        title={confirmModal.title}
        message={confirmModal.message}
        isConfirming={ackMutation.isPending || resolveMutation.isPending}
        onConfirm={confirmModal.action}
        onCancel={() => setConfirmModal((prev) => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
};
