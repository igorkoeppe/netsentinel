import React, { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useApiConfig } from "../hooks/useApiConfig";
import { listScans } from "../api/scans";
import { Pagination } from "../components/Pagination";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { EmptyState } from "../components/EmptyState";
import { formatDateTime, formatDurationMs } from "../utils/format";
import { Radar, Search, X } from "lucide-react";

export const ScansPage: React.FC = () => {
  const { client, pollInterval } = useApiConfig();
  const [searchParams, setSearchParams] = useSearchParams();

  const targetParam = searchParams.get("target") || undefined;
  const limitParam = parseInt(searchParams.get("limit") || "20", 10);
  const offsetParam = parseInt(searchParams.get("offset") || "0", 10);

  const [targetInput, setTargetInput] = useState(targetParam || "");

  const { data, isLoading, error } = useQuery({
    queryKey: ["scans", { target: targetParam, limit: limitParam, offset: offsetParam }],
    queryFn: () =>
      listScans(client, {
        target: targetParam,
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
    setTargetInput("");
    setSearchParams({});
  };

  const scans = data?.items || [];
  const hasTargetFilter = Boolean(targetParam);

  return (
    <div>
      {/* Target Filter Control */}
      <div
        className="card"
        style={{
          marginBottom: "1.25rem",
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "1rem",
        }}
      >
        <div style={{ maxWidth: "340px", flex: 1 }}>
          <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: "0.25rem" }}>
            Filter by Target
          </label>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              updateParam("target", targetInput || undefined);
            }}
            style={{ position: "relative" }}
          >
            <input
              type="text"
              className="input"
              placeholder="e.g. 192.168.1.1"
              value={targetInput}
              onChange={(e) => setTargetInput(e.target.value)}
              onBlur={() => updateParam("target", targetInput || undefined)}
              aria-label="Filter scans by target"
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

        {hasTargetFilter && (
          <button
            onClick={handleClearFilters}
            className="btn btn-sm"
            style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}
          >
            <X size={14} />
            <span>Reset filter</span>
          </button>
        )}
      </div>

      {/* Table Section */}
      {isLoading ? (
        <LoadingSpinner message="Loading monitoring scans..." />
      ) : error ? (
        <EmptyState
          title="Error Loading Scans"
          message={error instanceof Error ? error.message : "Failed to load scans."}
        />
      ) : scans.length === 0 ? (
        <EmptyState
          title="No Scans Found"
          message={
            hasTargetFilter
              ? `No scans recorded matching target '${targetParam}'.`
              : "No monitoring scans recorded in the database yet."
          }
          icon={<Radar size={36} />}
          action={
            hasTargetFilter ? (
              <button onClick={handleClearFilters} className="btn btn-sm">
                Clear filter
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
                  <th>ID</th>
                  <th>Target Address</th>
                  <th>Outcome</th>
                  <th>Response Time</th>
                  <th>Started At</th>
                  <th>Finished At</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {scans.map((scan) => (
                  <tr key={scan.id}>
                    <td>#{scan.id}</td>
                    <td>
                      <code>{scan.target}</code>
                    </td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          backgroundColor:
                            scan.status.toUpperCase() === "AVAILABLE"
                              ? "var(--color-success-bg)"
                              : "var(--color-danger-bg)",
                          color:
                            scan.status.toUpperCase() === "AVAILABLE"
                              ? "var(--color-success)"
                              : "var(--color-danger)",
                          border: `1px solid ${
                            scan.status.toUpperCase() === "AVAILABLE"
                              ? "var(--color-success)"
                              : "var(--color-danger)"
                          }`,
                        }}
                      >
                        {scan.status.toUpperCase()}
                      </span>
                    </td>
                    <td>{formatDurationMs(scan.response_time_ms)}</td>
                    <td title={scan.started_at}>{formatDateTime(scan.started_at)}</td>
                    <td title={scan.finished_at || undefined}>
                      {formatDateTime(scan.finished_at)}
                    </td>
                    <td>
                      <Link to={`/scans/${scan.id}`} className="btn btn-sm">
                        Details
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
            count={scans.length}
            onPageChange={(newOffset) => updateParam("offset", String(newOffset))}
            onLimitChange={(newLimit) => updateParam("limit", String(newLimit))}
            isLoading={isLoading}
          />
        </>
      )}
    </div>
  );
};
