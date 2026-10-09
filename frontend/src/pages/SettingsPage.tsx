import React, { useState } from "react";
import { useApiConfig } from "../hooks/useApiConfig";
import { useTheme } from "../hooks/useTheme";
import { type Theme } from "../providers/ThemeContext";
import { getHealthLive } from "../api/health";
import { listAlerts } from "../api/alerts";
import { Toast, ToastType } from "../components/Toast";
import {
  Key,
  Eye,
  EyeOff,
  Server,
  Palette,
  Clock,
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
  Trash2,
} from "lucide-react";

export const SettingsPage: React.FC = () => {
  const {
    baseUrl,
    setBaseUrl,
    apiKey,
    setApiKey,
    clearApiKey,
    rememberKeyInSession,
    setRememberKeyInSession,
    pollInterval,
    setPollInterval,
    client,
  } = useApiConfig();

  const { theme, setTheme } = useTheme();

  // Local state for form controls
  const [urlInput, setUrlInput] = useState(baseUrl);
  const [keyInput, setKeyInput] = useState(apiKey || "");
  const [showKey, setShowKey] = useState(false);
  const [rememberCheck, setRememberCheck] = useState(rememberKeyInSession);

  // Test connection state
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  // Feedback Toast
  const [toast, setToast] = useState<{ type: ToastType; message: string } | null>(null);

  const handleSaveConnection = (e: React.FormEvent) => {
    e.preventDefault();
    setBaseUrl(urlInput);
    setRememberKeyInSession(rememberCheck);
    setApiKey(keyInput, rememberCheck);
    setToast({
      type: "success",
      message: "Connection settings updated successfully.",
    });
  };

  const handleClearKey = () => {
    setKeyInput("");
    clearApiKey();
    setToast({
      type: "info",
      message: "API Key cleared from memory and session storage.",
    });
  };

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);

    try {
      // 1. Check live probe
      const live = await getHealthLive(client);
      if (live.status !== "ok") {
        throw new Error("Liveness check failed.");
      }

      // 2. Check auth with protected read endpoint
      try {
        await listAlerts(client, { limit: 1 });
        setTestResult({
          success: true,
          message: `Connected successfully to NetSentinel ${live.version}. Authentication valid!`,
        });
      } catch (authErr) {
        const status = (authErr as { status?: number }).status;
        if (status === 401) {
          setTestResult({
            success: false,
            message: "API server is online, but authentication failed (invalid or missing API Key).",
          });
        } else {
          setTestResult({
            success: true,
            message: `Connected to NetSentinel ${live.version}. (Alert read test: ${(authErr as Error).message})`,
          });
        }
      }
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Connection failed.",
      });
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <div style={{ maxWidth: "720px" }}>
      {toast && (
        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() => setToast(null)}
        />
      )}

      {/* Connection & Auth Section */}
      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
          <Server size={18} style={{ color: "var(--color-accent)" }} />
          <h2 style={{ fontSize: "1rem", fontWeight: 700 }}>API Connection & Credentials</h2>
        </div>

        <form onSubmit={handleSaveConnection}>
          {/* Base URL */}
          <div style={{ marginBottom: "1.25rem" }}>
            <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, marginBottom: "0.25rem" }}>
              API Base URL
            </label>
            <input
              type="text"
              className="input"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="/api/v1"
              aria-label="API Base URL"
            />
            <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
              Same-origin default is <code>/api/v1</code>. In development, Vite proxies requests to <code>http://127.0.0.1:8000</code>.
            </span>
          </div>

          {/* API Key */}
          <div style={{ marginBottom: "1.25rem" }}>
            <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, marginBottom: "0.25rem" }}>
              API Key
            </label>
            <div style={{ position: "relative" }}>
              <input
                type={showKey ? "text" : "password"}
                className="input"
                style={{ paddingRight: "40px" }}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                placeholder="Enter X-API-Key..."
                aria-label="API Key"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                style={{
                  position: "absolute",
                  right: "10px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: "var(--color-text-muted)",
                }}
                aria-label={showKey ? "Hide API key" : "Show API key"}
              >
                {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
              Key is attached via the <code>X-API-Key</code> request header. It is never included in URLs or query parameters.
            </span>
          </div>

          {/* Remember in session checkbox */}
          <div style={{ marginBottom: "1.5rem" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.8125rem", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={rememberCheck}
                onChange={(e) => setRememberCheck(e.target.checked)}
              />
              <span>Remember for this browser tab (stored in <code>sessionStorage</code>, never <code>localStorage</code>)</span>
            </label>
          </div>

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <button type="submit" className="btn btn-primary btn-sm">
              <Key size={14} />
              <span>Save Credentials</span>
            </button>

            {apiKey && (
              <button
                type="button"
                onClick={handleClearKey}
                className="btn btn-sm"
                style={{ color: "var(--color-danger)" }}
              >
                <Trash2 size={14} />
                <span>Clear API Key</span>
              </button>
            )}

            <button
              type="button"
              onClick={handleTestConnection}
              disabled={isTesting}
              className="btn btn-sm"
              style={{ marginLeft: "auto" }}
            >
              <ShieldCheck size={14} />
              <span>{isTesting ? "Testing..." : "Test Connection"}</span>
            </button>
          </div>
        </form>

        {/* Connection Test Result */}
        {testResult && (
          <div
            style={{
              marginTop: "1rem",
              padding: "0.75rem 1rem",
              borderRadius: "var(--radius-sm)",
              backgroundColor: testResult.success ? "var(--color-success-bg)" : "var(--color-danger-bg)",
              border: `1px solid ${testResult.success ? "var(--color-success)" : "var(--color-danger)"}`,
              fontSize: "0.8125rem",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            {testResult.success ? (
              <CheckCircle2 size={16} style={{ color: "var(--color-success)" }} />
            ) : (
              <AlertCircle size={16} style={{ color: "var(--color-danger)" }} />
            )}
            <span>{testResult.message}</span>
          </div>
        )}
      </div>

      {/* Preferences Section: Theme and Polling */}
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
          <Palette size={18} style={{ color: "var(--color-accent)" }} />
          <h2 style={{ fontSize: "1rem", fontWeight: 700 }}>Dashboard Preferences</h2>
        </div>

        {/* Theme Preference */}
        <div style={{ marginBottom: "1.25rem" }}>
          <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, marginBottom: "0.25rem" }}>
            Visual Theme
          </label>
          <select
            value={theme}
            onChange={(e) => setTheme(e.target.value as Theme)}
            aria-label="Select theme"
          >
            <option value="system">System (Default)</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
          <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
            Respects <code>prefers-color-scheme</code> when set to System. Persisted in localStorage.
          </span>
        </div>

        {/* Polling Interval */}
        <div>
          <label style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.8125rem", fontWeight: 600, marginBottom: "0.25rem" }}>
            <Clock size={14} />
            <span>Automatic Polling Interval</span>
          </label>
          <select
            value={pollInterval}
            onChange={(e) => setPollInterval(Number(e.target.value))}
            aria-label="Select polling interval"
          >
            <option value={0}>Off (Manual refresh)</option>
            <option value={5000}>5 seconds</option>
            <option value={10000}>10 seconds (Default)</option>
            <option value={30000}>30 seconds</option>
            <option value={60000}>60 seconds</option>
          </select>
          <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
            Polling pauses automatically when the browser tab is inactive.
          </span>
        </div>
      </div>
    </div>
  );
};
