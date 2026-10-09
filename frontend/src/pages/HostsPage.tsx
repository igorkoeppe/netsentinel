import React, { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useApiConfig } from "../hooks/useApiConfig";
import { listHosts } from "../api/hosts";
import { BooleanBadge } from "../components/Badge";
import { Pagination } from "../components/Pagination";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { EmptyState } from "../components/EmptyState";
import { formatDateTime } from "../utils/format";
import { Search, X, Server } from "lucide-react";

export const HostsPage: React.FC = () => {
  const { client, pollInterval } = useApiConfig();
  const [searchParams, setSearchParams] = useSearchParams();

  const qParam = searchParams.get("q") || undefined;
  const enabledParam = searchParams.get("enabled");
  const limitParam = parseInt(searchParams.get("limit") || "20", 10);
  const offsetParam = parseInt(searchParams.get("offset") || "0", 10);

  const [qInput, setQInput] = useState(qParam || "");

  const enabledFilter: boolean | undefined =
    enabledParam === "true" ? true : enabledParam === "false" ? false : undefined;

  const { data, isLoading, error } = useQuery({
    queryKey: ["hosts", { q: qParam, enabled: enabledFilter, limit: limitParam, offset: offsetParam }],
    queryFn: () =>
      listHosts(client, {
        q: qParam,
        enabled: enabledFilter,
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
    if (key !== "offset" && key !== "limit") {
      next.delete("offset");
    }
    setSearchParams(next);
  };

  const handleClearFilters = () => {
    setQInput("");
    setSearchParams({});
  };

  const hosts = data?.items || [];
  const hasFilters = Boolean(qParam || enabledParam !== null);

  return (
    <div>
      {/* Search and Filter Controls */}
      <div
        className="card"
        style={{
          marginBottom: "1.25rem",
          display: "flex",
          flexWrap: "wrap",
          gap: "1rem",
          alignItems: "flex-end",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", flex: 1, maxWidth: "600px" }}>
          {/* Server-side Search input */}
          <div style={{ flex: "1 1 240px" }}>
            <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: "0.25rem" }}>
              Search Host
            </label>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                updateParam("q", qInput || undefined);
              }}
              style={{ position: "relative" }}
            >
              <input
                type="text"
                className="input"
                placeholder="Search name or address..."
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
                onBlur={() => updateParam("q", qInput || undefined)}
                aria-label="Search hosts"
              />
              <button
                type="submit"
                style={{
                  position: "absolute",
                  right: "8px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: "var(--color-text-muted)",
                }}
                aria-label="Submit search"
              >
                <Search size={16} />
              </button>
            </form>
          </div>

          {/* Enabled Status Dropdown */}
          <div style={{ width: "160px" }}>
            <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: "0.25rem" }}>
              State
            </label>
            <select
              value={enabledParam || ""}
              onChange={(e) => updateParam("enabled", e.target.value || undefined)}
              aria-label="Filter by active state"
            >
              <option value="">All Hosts</option>
              <option value="true">Active Only</option>
              <option value="false">Disabled Only</option>
            </select>
          </div>
        </div>

        {hasFilters && (
          <button
            onClick={handleClearFilters}
            className="btn btn-sm"
            style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}
          >
            <X size={14} />
            <span>Reset filters</span>
          </button>
        )}
      </div>

      {/* Table Section */}
      {isLoading ? (
        <LoadingSpinner message="Loading hosts..." />
      ) : error ? (
        <EmptyState
          title="Error Loading Hosts"
          message={error instanceof Error ? error.message : "Failed to load hosts."}
        />
      ) : hosts.length === 0 ? (
        <EmptyState
          title="No hosts found"
          message={
            hasFilters
              ? "No registered hosts match the current search or filter."
              : "No monitored hosts registered yet."
          }
          icon={<Server size={36} />}
          action={
            hasFilters ? (
              <button onClick={handleClearFilters} className="btn btn-sm">
                Clear filters
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
                  <th>Address</th>
                  <th>Name / Label</th>
                  <th>Status</th>
                  <th>Registered</th>
                  <th>Last Updated</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {hosts.map((host) => (
                  <tr key={host.id}>
                    <td>
                      <code style={{ fontSize: "0.875rem", fontWeight: 600 }}>
                        {host.address}
                      </code>
                    </td>
                    <td>{host.name || "—"}</td>
                    <td>
                      <BooleanBadge value={host.enabled} />
                    </td>
                    <td title={host.created_at}>{formatDateTime(host.created_at)}</td>
                    <td title={host.updated_at || undefined}>
                      {formatDateTime(host.updated_at)}
                    </td>
                    <td>
                      <Link
                        to={`/hosts/${encodeURIComponent(host.address)}`}
                        className="btn btn-sm"
                      >
                        History
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            offset={offsetParam}
            limit={limitParam}
            count={hosts.length}
            onPageChange={(newOffset) => updateParam("offset", String(newOffset))}
            onLimitChange={(newLimit) => updateParam("limit", String(newLimit))}
            isLoading={isLoading}
          />
        </>
      )}
    </div>
  );
};
