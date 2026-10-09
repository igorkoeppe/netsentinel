import React, { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Shield,
  LayoutDashboard,
  Bell,
  Server,
  Radar,
  Settings,
  Menu,
  X,
  Key,
} from "lucide-react";
import { HealthIndicator } from "../components/HealthIndicator";
import { useApiConfig } from "../hooks/useApiConfig";

export const Layout: React.FC = () => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const location = useLocation();
  const { apiKey } = useApiConfig();

  const getPageTitle = () => {
    const path = location.pathname;
    if (path === "/") return "Operational Overview";
    if (path.startsWith("/alerts/")) return "Alert Details";
    if (path.startsWith("/alerts")) return "Security Alerts";
    if (path.startsWith("/hosts/")) return "Host History";
    if (path.startsWith("/hosts")) return "Monitored Hosts";
    if (path.startsWith("/scans/")) return "Scan Details";
    if (path.startsWith("/scans")) return "Monitoring Scans";
    if (path.startsWith("/settings")) return "Settings & Connection";
    return "NetSentinel";
  };

  const navItems = [
    { to: "/", label: "Overview", icon: <LayoutDashboard size={18} /> },
    { to: "/alerts", label: "Alerts", icon: <Bell size={18} /> },
    { to: "/hosts", label: "Hosts", icon: <Server size={18} /> },
    { to: "/scans", label: "Scans", icon: <Radar size={18} /> },
    { to: "/settings", label: "Settings", icon: <Settings size={18} /> },
  ];

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside
        className={`sidebar ${mobileMenuOpen ? "mobile-open" : ""}`}
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "1.25rem 1rem",
        }}
      >
        <div>
          {/* Brand header */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.625rem",
              marginBottom: "1.75rem",
              paddingLeft: "0.5rem",
            }}
          >
            <div
              style={{
                backgroundColor: "var(--color-accent)",
                color: "#ffffff",
                padding: "0.4rem",
                borderRadius: "var(--radius-sm)",
                display: "flex",
                alignItems: "center",
              }}
            >
              <Shield size={20} />
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: "1.125rem", letterSpacing: "-0.02em" }}>
                NetSentinel
              </div>
              <div
                style={{
                  fontSize: "0.6875rem",
                  color: "var(--color-text-muted)",
                  textTransform: "uppercase",
                  fontWeight: 600,
                  letterSpacing: "0.05em",
                }}
              >
                v0.8.0
              </div>
            </div>
          </div>

          {/* Navigation Links */}
          <nav aria-label="Main Navigation">
            <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: "0.25rem" }}>
              {navItems.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/"}
                    onClick={() => setMobileMenuOpen(false)}
                    style={({ isActive }) => ({
                      display: "flex",
                      alignItems: "center",
                      gap: "0.75rem",
                      padding: "0.625rem 0.75rem",
                      borderRadius: "var(--radius-sm)",
                      color: isActive ? "var(--color-accent)" : "var(--color-text)",
                      backgroundColor: isActive ? "var(--color-accent-subtle)" : "transparent",
                      fontWeight: isActive ? 600 : 500,
                      textDecoration: "none",
                      fontSize: "0.875rem",
                      transition: "background-color var(--transition-fast)",
                    })}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </div>

        {/* Sidebar Footer info */}
        <div
          style={{
            borderTop: "1px solid var(--color-border)",
            paddingTop: "0.875rem",
            fontSize: "0.75rem",
            color: "var(--color-text-muted)",
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
          }}
        >
          {apiKey ? (
            <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", color: "var(--color-success)" }}>
              <Key size={14} />
              <span>API Key Active</span>
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", color: "var(--color-text-muted)" }}>
              <Key size={14} />
              <span>No Key (Dev Mode)</span>
            </div>
          )}
          <div>Defensive SOC Platform</div>
        </div>
      </aside>

      {/* Main Container */}
      <div className="main-content">
        <header className="topbar">
          <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
            <button
              className="btn btn-sm"
              style={{ display: "none" }}
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label="Toggle menu"
            >
              {mobileMenuOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
            <h1 style={{ fontSize: "1.125rem", fontWeight: 700, margin: 0 }}>
              {getPageTitle()}
            </h1>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
            <HealthIndicator />
          </div>
        </header>

        <main className="page-container">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
