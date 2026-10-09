import React from "react";
import { Link } from "react-router-dom";
import { ShieldAlert, ArrowLeft } from "lucide-react";

export const NotFoundPage: React.FC = () => {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "50vh",
        textAlign: "center",
        padding: "2rem",
      }}
    >
      <div
        style={{
          padding: "1rem",
          borderRadius: "50%",
          backgroundColor: "var(--color-surface-hover)",
          color: "var(--color-text-muted)",
          marginBottom: "1rem",
        }}
      >
        <ShieldAlert size={48} />
      </div>
      <h2 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.5rem" }}>
        Page Not Found
      </h2>
      <p
        style={{
          fontSize: "0.875rem",
          color: "var(--color-text-muted)",
          maxWidth: "400px",
          marginBottom: "1.5rem",
        }}
      >
        The requested URL was not found on this NetSentinel dashboard.
      </p>
      <Link to="/" className="btn btn-primary btn-sm">
        <ArrowLeft size={16} />
        <span>Return to Overview</span>
      </Link>
    </div>
  );
};
