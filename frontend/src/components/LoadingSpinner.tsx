import React from "react";
import { Loader2 } from "lucide-react";

export const LoadingSpinner: React.FC<{ size?: number; message?: string }> = ({
  size = 24,
  message,
}) => {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem",
        gap: "0.75rem",
        color: "var(--color-text-muted)",
      }}
      role="status"
      aria-live="polite"
    >
      <Loader2
        size={size}
        style={{
          animation: "spin 1s linear infinite",
          color: "var(--color-accent)",
        }}
      />
      {message && <span style={{ fontSize: "0.875rem" }}>{message}</span>}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

export const Skeleton: React.FC<{
  height?: string | number;
  width?: string | number;
  borderRadius?: string;
}> = ({ height = "1rem", width = "100%", borderRadius = "var(--radius-sm)" }) => {
  return (
    <div
      style={{
        height,
        width,
        borderRadius,
        backgroundColor: "var(--color-border)",
        opacity: 0.6,
        animation: "pulse 1.5s ease-in-out infinite",
      }}
    >
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 0.8; }
        }
      `}</style>
    </div>
  );
};
