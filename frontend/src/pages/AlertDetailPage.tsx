import React, { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiConfig } from "../hooks/useApiConfig";
import {
  getAlert,
  getAlertDeliveries,
  acknowledgeAlert,
  resolveAlert,
} from "../api/alerts";
import { type NotificationDeliveryResponse } from "../api/types";
import { SeverityBadge, StatusBadge } from "../components/Badge";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { EmptyState } from "../components/EmptyState";
import { Toast, ToastType } from "../components/Toast";
import { ConfirmModal } from "../components/ConfirmModal";
import { formatDateTime, formatPort } from "../utils/format";
import {
  ArrowLeft,
  Clock,
  CheckCircle,
  Radio,
  ExternalLink,
} from "lucide-react";

export const AlertDetailPage: React.FC = () => {
  const { alertId } = useParams<{ alertId: string }>();
  const idNumber = parseInt(alertId || "0", 10);
  const { client, pollInterval } = useApiConfig();
  const queryClient = useQueryClient();

  const [toast, setToast] = useState<{ type: ToastType; message: string } | null>(null);
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

  const {
    data: alert,
    isLoading: alertLoading,
    error: alertError,
    refetch: refetchAlert,
  } = useQuery({
    queryKey: ["alert", idNumber],
    queryFn: () => getAlert(client, idNumber),
    enabled: idNumber > 0,
    refetchInterval: pollInterval > 0 ? pollInterval : false,
  });

  const {
    data: deliveries,
    isLoading: deliveriesLoading,
    error: deliveriesError,
    refetch: refetchDeliveries,
  } = useQuery({
    queryKey: ["alert-deliveries", idNumber],
    queryFn: () => getAlertDeliveries(client, idNumber),
    enabled: idNumber > 0,
    refetchInterval: pollInterval > 0 ? pollInterval : false,
  });

  const deliveryList = Array.isArray(deliveries)
    ? deliveries
    : deliveries && typeof deliveries === "object" && "items" in deliveries && Array.isArray((deliveries as { items?: unknown[] }).items)
      ? (deliveries as { items: NotificationDeliveryResponse[] }).items
      : [];

  const ackMutation = useMutation({
    mutationFn: () => acknowledgeAlert(client, idNumber),
    onSuccess: (updated) => {
      setToast({
        type: "success",
        message: `Alert #${updated.id} acknowledged successfully.`,
      });
      queryClient.invalidateQueries({ queryKey: ["alert", idNumber] });
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
        refetchAlert();
      } else {
        const msg = err instanceof Error ? err.message : "Failed to acknowledge alert.";
        setToast({ type: "error", message: msg });
      }
    },
  });

  const resolveMutation = useMutation({
    mutationFn: () => resolveAlert(client, idNumber),
    onSuccess: (updated) => {
      setToast({
        type: "success",
        message: `Alert #${updated.id} resolved successfully.`,
      });
      queryClient.invalidateQueries({ queryKey: ["alert", idNumber] });
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
        refetchAlert();
      } else {
        const msg = err instanceof Error ? err.message : "Failed to resolve alert.";
        setToast({ type: "error", message: msg });
      }
    },
  });

  if (idNumber <= 0) {
    return (
      <EmptyState
        title="Invalid Alert ID"
        message="The requested alert ID must be a positive integer."
        action={
          <Link to="/alerts" className="btn btn-primary btn-sm">
            Back to Alerts
          </Link>
        }
      />
    );
  }

  if (alertLoading) {
    return <LoadingSpinner message={`Loading alert #${idNumber}...`} />;
  }

  if (alertError || !alert) {
    const status = (alertError as { status?: number })?.status;
    let title = "Unable to load alert";
    let message = "Unable to load alert details.";

    if (status === 401) {
      title = "Authentication required";
      message =
        "Authentication required or API key invalid. Please configure your API key in Settings.";
    } else if (status === 404 || (!alertError && !alert)) {
      title = "Alert Not Found";
      message = `Alert #${idNumber} not found.`;
    } else if (status === 500) {
      title = "Unable to load alert";
      message =
        alertError instanceof Error
          ? alertError.message
          : "An internal server error occurred while loading alert details.";
    } else if (alertError instanceof Error) {
      message = alertError.message;
    }

    return (
      <EmptyState
        title={title}
        message={message}
        action={
          <Link to="/alerts" className="btn btn-primary btn-sm">
            Back to Alerts
          </Link>
        }
      />
    );
  }

  const isAckDisabled = alert.status !== "OPEN" || ackMutation.isPending;
  const isResolveDisabled =
    alert.status === "RESOLVED" || resolveMutation.isPending;

  return (
    <div>
      {/* Back button & Title */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
        <Link to="/alerts" className="btn btn-sm" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
          <ArrowLeft size={16} />
          <span>Back to Alerts</span>
        </Link>

        {/* Action buttons */}
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {alert.status === "OPEN" && (
            <button
              className="btn btn-sm"
              style={{ color: "var(--color-warning)" }}
              onClick={() =>
                setConfirmModal({
                  isOpen: true,
                  title: `Acknowledge Alert #${alert.id}`,
                  message: `Mark alert #${alert.id} as ACKNOWLEDGED?`,
                  action: () => ackMutation.mutate(),
                })
              }
              disabled={isAckDisabled}
            >
              <Clock size={16} />
              <span>{ackMutation.isPending ? "Acknowledging..." : "Acknowledge"}</span>
            </button>
          )}

          {alert.status !== "RESOLVED" && (
            <button
              className="btn btn-success btn-sm"
              onClick={() =>
                setConfirmModal({
                  isOpen: true,
                  title: `Resolve Alert #${alert.id}`,
                  message: `Mark alert #${alert.id} as RESOLVED?`,
                  action: () => resolveMutation.mutate(),
                })
              }
              disabled={isResolveDisabled}
            >
              <CheckCircle size={16} />
              <span>{resolveMutation.isPending ? "Resolving..." : "Resolve"}</span>
            </button>
          )}
        </div>
      </div>

      {toast && (
        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() => setToast(null)}
        />
      )}

      {/* Main Alert Card */}
      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
          <h2 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Alert #{alert.id}</h2>
          <SeverityBadge severity={alert.severity} />
          <StatusBadge status={alert.status} />
        </div>

        {/* Message Banner */}
        <div
          style={{
            padding: "0.875rem 1rem",
            backgroundColor: "var(--color-surface-hover)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-sm)",
            fontSize: "0.9375rem",
            marginBottom: "1.5rem",
            lineHeight: 1.5,
          }}
        >
          {alert.message}
        </div>

        {/* Details Grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "1.25rem",
            fontSize: "0.875rem",
          }}
        >
          <div>
            <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
              Rule Type
            </div>
            <div style={{ fontWeight: 600, marginTop: "0.25rem" }}>
              <code>{alert.alert_type}</code>
            </div>
          </div>

          <div>
            <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
              Target Host
            </div>
            <div style={{ fontWeight: 600, marginTop: "0.25rem" }}>
              <Link to={`/hosts/${encodeURIComponent(alert.target)}`} style={{ color: "var(--color-accent)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
                <span>{alert.target}</span>
                <ExternalLink size={12} />
              </Link>
            </div>
          </div>

          <div>
            <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
              TCP Port
            </div>
            <div style={{ fontWeight: 600, marginTop: "0.25rem" }}>
              {formatPort(alert.port)}
            </div>
          </div>

          <div>
            <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
              Associated Scan
            </div>
            <div style={{ fontWeight: 600, marginTop: "0.25rem" }}>
              {alert.scan_id ? (
                <Link to={`/scans/${alert.scan_id}`} style={{ color: "var(--color-accent)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
                  <span>Scan #{alert.scan_id}</span>
                  <ExternalLink size={12} />
                </Link>
              ) : (
                "—"
              )}
            </div>
          </div>

          <div>
            <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
              Created At
            </div>
            <div style={{ marginTop: "0.25rem" }} title={alert.created_at}>
              {formatDateTime(alert.created_at)}
            </div>
          </div>

          <div>
            <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
              Acknowledged At
            </div>
            <div style={{ marginTop: "0.25rem" }} title={alert.acknowledged_at || undefined}>
              {formatDateTime(alert.acknowledged_at)}
            </div>
          </div>

          <div>
            <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem", textTransform: "uppercase", fontWeight: 600 }}>
              Resolved At
            </div>
            <div style={{ marginTop: "0.25rem" }} title={alert.resolved_at || undefined}>
              {formatDateTime(alert.resolved_at)}
            </div>
          </div>
        </div>
      </div>

      {/* Notification Deliveries Section */}
      <div style={{ marginTop: "2rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <Radio size={18} style={{ color: "var(--color-accent)" }} />
          <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>Notification Delivery Audit</h3>
        </div>

        {deliveriesLoading ? (
          <LoadingSpinner size={20} message="Loading notification delivery history..." />
        ) : deliveriesError ? (
          <EmptyState
            title="Unable to load delivery history"
            message={deliveriesError instanceof Error ? deliveriesError.message : "Failed to load notification deliveries."}
            action={<button className="btn btn-sm" onClick={() => void refetchDeliveries()}>Retry delivery history</button>}
          />
        ) : deliveryList.length === 0 ? (
          <EmptyState
            title="No deliveries recorded"
            message="No notification dispatches have been attempted for this alert."
          />
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Channel</th>
                  <th>Outcome</th>
                  <th>Attempts</th>
                  <th>Timestamp</th>
                  <th>Error / Diagnostic Details</th>
                </tr>
              </thead>
              <tbody>
                {deliveryList.map((delivery) => (
                  <tr key={delivery.id}>
                    <td>
                      <code style={{ fontSize: "0.8125rem", textTransform: "uppercase" }}>
                        {delivery.channel}
                      </code>
                    </td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          backgroundColor: delivery.success
                            ? "var(--color-success-bg)"
                            : "var(--color-danger-bg)",
                          color: delivery.success
                            ? "var(--color-success)"
                            : "var(--color-danger)",
                          border: `1px solid ${
                            delivery.success
                              ? "var(--color-success)"
                              : "var(--color-danger)"
                          }`,
                        }}
                      >
                        {delivery.success ? "SUCCESS" : "FAILED"}
                      </span>
                    </td>
                    <td>{delivery.attempts}</td>
                    <td title={delivery.created_at}>{formatDateTime(delivery.created_at)}</td>
                    <td style={{ color: delivery.error ? "var(--color-danger)" : "var(--color-text-muted)" }}>
                      {delivery.error || "None"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Confirmation Modal */}
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
