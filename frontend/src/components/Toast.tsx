import React from "react";
import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";

export type ToastType = "success" | "error" | "info" | "warning";

interface ToastProps {
  type?: ToastType;
  message: string;
  onClose?: () => void;
}

export const Toast: React.FC<ToastProps> = ({
  type = "info",
  message,
  onClose,
}) => {
  let bg = "var(--color-info-bg)";
  let border = "var(--color-info)";
  let color = "var(--color-info)";
  let icon = <Info size={18} />;

  switch (type) {
    case "success":
      bg = "var(--color-success-bg)";
      border = "var(--color-success)";
      color = "var(--color-success)";
      icon = <CheckCircle2 size={18} />;
      break;
    case "error":
      bg = "var(--color-danger-bg)";
      border = "var(--color-danger)";
      color = "var(--color-danger)";
      icon = <AlertCircle size={18} />;
      break;
    case "warning":
      bg = "var(--color-warning-bg)";
      border = "var(--color-warning)";
      color = "var(--color-warning)";
      icon = <AlertCircle size={18} />;
      break;
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "0.75rem",
        padding: "0.75rem 1rem",
        borderRadius: "var(--radius-sm)",
        backgroundColor: bg,
        border: `1px solid ${border}`,
        color: "var(--color-text)",
        fontSize: "0.875rem",
        margin: "0.75rem 0",
      }}
      role="alert"
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span style={{ color, display: "flex", alignItems: "center" }}>{icon}</span>
        <span>{message}</span>
      </div>
      {onClose && (
        <button
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--color-text-muted)",
            display: "flex",
            alignItems: "center",
          }}
          aria-label="Dismiss alert message"
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
};
