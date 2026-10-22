import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Plus } from "lucide-react";
import { useApiConfig } from "../hooks/useApiConfig";
import { createSchedule, listSchedules, parsePortList, updateSchedule } from "../api/schedules";
import type { ScheduleResponse } from "../api/types";
import { BooleanBadge } from "../components/Badge";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { EmptyState } from "../components/EmptyState";
import { Toast, ToastType } from "../components/Toast";
import { formatDateTime } from "../utils/format";

const DEFAULT_INTERVAL_SECONDS = 300;

function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "0.75rem",
  fontWeight: 600,
  color: "var(--color-text-muted)",
  marginBottom: "0.25rem",
};

export const SchedulesPage: React.FC = () => {
  const { client, pollInterval } = useApiConfig();
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<{ type: ToastType; message: string } | null>(null);
  const [target, setTarget] = useState("");
  const [ports, setPorts] = useState("");
  const [interval, setIntervalSeconds] = useState(String(DEFAULT_INTERVAL_SECONDS));

  const { data, isLoading, error } = useQuery({
    queryKey: ["schedules"],
    queryFn: () => listSchedules(client, { limit: 100 }),
    refetchInterval: pollInterval > 0 ? pollInterval : false,
  });

  const showError = (err: unknown, fallback: string) => {
    setToast({ type: "error", message: err instanceof Error ? err.message : fallback });
  };

  const createMutation = useMutation({
    mutationFn: (body: { target: string; ports: number[]; interval_seconds: number }) =>
      createSchedule(client, body),
    onSuccess: (created) => {
      setToast({ type: "success", message: `Schedule created for ${created.target}.` });
      setTarget("");
      setPorts("");
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
    onError: (err: unknown) => showError(err, "Failed to create schedule."),
  });

  const toggleMutation = useMutation({
    mutationFn: (schedule: ScheduleResponse) =>
      updateSchedule(client, schedule.id, { enabled: !schedule.enabled }),
    onSuccess: (updated) => {
      setToast({
        type: "success",
        message: `Schedule for ${updated.target} ${updated.enabled ? "enabled" : "disabled"}.`,
      });
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
    onError: (err: unknown) => showError(err, "Failed to update schedule."),
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    const parsedPorts = parsePortList(ports);
    const intervalSeconds = Number(interval);
    if (!target.trim()) {
      setToast({ type: "error", message: "Target is required." });
      return;
    }
    if (parsedPorts === null) {
      setToast({
        type: "error",
        message: "Ports must be a comma-separated list of numbers between 1 and 65535.",
      });
      return;
    }
    if (!Number.isInteger(intervalSeconds) || intervalSeconds <= 0) {
      setToast({ type: "error", message: "Interval must be a positive number of seconds." });
      return;
    }
    createMutation.mutate({
      target: target.trim(),
      ports: parsedPorts,
      interval_seconds: intervalSeconds,
    });
  };

  const schedules = data?.items || [];

  return (
    <div>
      {toast && (
        <Toast type={toast.type} message={toast.message} onClose={() => setToast(null)} />
      )}

      <form
        className="card"
        onSubmit={handleCreate}
        style={{
          marginBottom: "1.25rem",
          display: "flex",
          flexWrap: "wrap",
          gap: "1rem",
          alignItems: "flex-end",
        }}
      >
        <div style={{ flex: "1 1 200px" }}>
          <label htmlFor="schedule-target" style={labelStyle}>
            Target
          </label>
          <input
            id="schedule-target"
            className="input"
            placeholder="192.168.1.10 or host.lan"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
        </div>
        <div style={{ flex: "1 1 200px" }}>
          <label htmlFor="schedule-ports" style={labelStyle}>
            TCP ports
          </label>
          <input
            id="schedule-ports"
            className="input"
            placeholder="22,80,443"
            value={ports}
            onChange={(e) => setPorts(e.target.value)}
          />
        </div>
        <div style={{ width: "140px" }}>
          <label htmlFor="schedule-interval" style={labelStyle}>
            Interval (seconds)
          </label>
          <input
            id="schedule-interval"
            className="input"
            type="number"
            min={1}
            value={interval}
            onChange={(e) => setIntervalSeconds(e.target.value)}
          />
        </div>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={createMutation.isPending}
          style={{ display: "inline-flex", alignItems: "center", gap: "0.375rem" }}
        >
          <Plus size={16} />
          <span>{createMutation.isPending ? "Creating..." : "Add schedule"}</span>
        </button>
      </form>

      {isLoading ? (
        <LoadingSpinner message="Loading schedules..." />
      ) : error ? (
        <EmptyState
          title="Error Loading Schedules"
          message={error instanceof Error ? error.message : "Failed to load schedules."}
        />
      ) : schedules.length === 0 ? (
        <EmptyState
          title="No scan schedules"
          message="Add a target above to scan it periodically. New open ports and closed ports raise alerts."
          icon={<CalendarClock size={36} />}
        />
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Target</th>
                <th>Ports</th>
                <th>Every</th>
                <th>Status</th>
                <th>Next run</th>
                <th>Last run</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((schedule) => (
                <tr key={schedule.id}>
                  <td>
                    <Link to={`/hosts/${encodeURIComponent(schedule.target)}`}>
                      <code style={{ fontSize: "0.875rem", fontWeight: 600 }}>
                        {schedule.target}
                      </code>
                    </Link>
                    {schedule.name && (
                      <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                        {schedule.name}
                      </div>
                    )}
                  </td>
                  <td>
                    <code style={{ fontSize: "0.8125rem" }}>{schedule.ports.join(", ")}</code>
                  </td>
                  <td>{formatInterval(schedule.interval_seconds)}</td>
                  <td>
                    <BooleanBadge value={schedule.enabled} />
                  </td>
                  <td title={schedule.next_run_at}>
                    {schedule.enabled ? formatDateTime(schedule.next_run_at) : "—"}
                  </td>
                  <td title={schedule.last_run_at || undefined}>
                    {schedule.last_scan_id !== null && !schedule.last_error ? (
                      <Link to={`/scans/${schedule.last_scan_id}`}>
                        {formatDateTime(schedule.last_run_at)}
                      </Link>
                    ) : (
                      formatDateTime(schedule.last_run_at)
                    )}
                    {schedule.last_error && (
                      <div
                        role="note"
                        style={{ fontSize: "0.75rem", color: "var(--color-danger)" }}
                      >
                        {schedule.last_error}
                      </div>
                    )}
                  </td>
                  <td>
                    <button
                      className="btn btn-sm"
                      disabled={toggleMutation.isPending}
                      onClick={() => toggleMutation.mutate(schedule)}
                      aria-label={`${schedule.enabled ? "Disable" : "Enable"} schedule for ${schedule.target}`}
                    >
                      {schedule.enabled ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
