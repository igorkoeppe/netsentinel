import React from "react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  title?: string;
  message: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = "No data found",
  message,
  icon = <Inbox size={36} />,
  action,
}) => {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "3rem 1.5rem",
        textAlign: "center",
        backgroundColor: "var(--color-surface)",
        border: "1px dashed var(--color-border)",
        borderRadius: "var(--radius-md)",
        color: "var(--color-text-muted)",
        margin: "1rem 0",
      }}
    >
      <div style={{ marginBottom: "1rem", color: "var(--color-text-muted)", opacity: 0.8 }}>
        {icon}
      </div>
      <h3 style={{ fontSize: "1.125rem", fontWeight: 600, color: "var(--color-text)", marginBottom: "0.25rem" }}>
        {title}
      </h3>
      <p style={{ fontSize: "0.875rem", maxWidth: "450px", marginBottom: action ? "1.25rem" : 0 }}>
        {message}
      </p>
      {action && <div>{action}</div>}
    </div>
  );
};
