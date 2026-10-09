import React from "react";
import { AlertSeverity, AlertStatus } from "../api/types";

export const SeverityBadge: React.FC<{ severity: AlertSeverity | string }> = ({
  severity,
}) => {
  const norm = severity.toUpperCase();
  let bg = "var(--color-info-bg)";
  let color = "var(--color-info)";

  switch (norm) {
    case "CRITICAL":
      bg = "var(--color-critical-bg)";
      color = "var(--color-critical)";
      break;
    case "HIGH":
      bg = "var(--color-high-bg)";
      color = "var(--color-high)";
      break;
    case "MEDIUM":
      bg = "var(--color-medium-bg)";
      color = "var(--color-medium)";
      break;
    case "LOW":
      bg = "var(--color-low-bg)";
      color = "var(--color-low)";
      break;
    case "INFO":
    default:
      bg = "var(--color-info-bg)";
      color = "var(--color-info)";
      break;
  }

  return (
    <span
      className="badge"
      style={{ backgroundColor: bg, color, border: `1px solid ${color}` }}
      aria-label={`Severity: ${norm}`}
    >
      {norm}
    </span>
  );
};

export const StatusBadge: React.FC<{ status: AlertStatus | string }> = ({
  status,
}) => {
  const norm = status.toUpperCase();
  let bg = "var(--color-high-bg)";
  let color = "var(--color-high)";

  switch (norm) {
    case "RESOLVED":
      bg = "var(--color-success-bg)";
      color = "var(--color-success)";
      break;
    case "ACKNOWLEDGED":
      bg = "var(--color-warning-bg)";
      color = "var(--color-warning)";
      break;
    case "OPEN":
    default:
      bg = "var(--color-danger-bg)";
      color = "var(--color-danger)";
      break;
  }

  return (
    <span
      className="badge"
      style={{ backgroundColor: bg, color, border: `1px solid ${color}` }}
      aria-label={`Status: ${norm}`}
    >
      {norm}
    </span>
  );
};

export const BooleanBadge: React.FC<{
  value: boolean;
  trueText?: string;
  falseText?: string;
}> = ({ value, trueText = "Active", falseText = "Disabled" }) => {
  const bg = value ? "var(--color-success-bg)" : "var(--color-surface-hover)";
  const color = value ? "var(--color-success)" : "var(--color-text-muted)";
  const text = value ? trueText : falseText;

  return (
    <span
      className="badge"
      style={{ backgroundColor: bg, color, border: `1px solid ${color}` }}
      aria-label={text}
    >
      {text}
    </span>
  );
};
