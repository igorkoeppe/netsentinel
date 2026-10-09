import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
  };

  public static getDerivedStateFromError(_: Error): State {
    return { hasError: true };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // In dev, log error without leaking secrets
    if (import.meta.env.DEV) {
      console.error("ErrorBoundary caught:", error.message, errorInfo.componentStack);
    }
  }

  public render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "60vh",
            padding: "2rem",
            textAlign: "center",
          }}
        >
          <div
            style={{
              padding: "1rem",
              borderRadius: "50%",
              backgroundColor: "var(--color-danger-bg)",
              color: "var(--color-danger)",
              marginBottom: "1rem",
            }}
          >
            <AlertTriangle size={40} />
          </div>
          <h2 style={{ fontSize: "1.25rem", fontWeight: 700, marginBottom: "0.5rem" }}>
            Something went wrong
          </h2>
          <p
            style={{
              fontSize: "0.875rem",
              color: "var(--color-text-muted)",
              maxWidth: "460px",
              marginBottom: "1.5rem",
            }}
          >
            An unexpected error occurred while rendering this view. You can reload the page to recover.
          </p>
          <button
            className="btn btn-primary"
            onClick={() => window.location.reload()}
          >
            <RefreshCw size={16} />
            <span>Reload page</span>
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
