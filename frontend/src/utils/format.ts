/**
 * Formatting utilities for timestamps, durations, and defensive status mappings.
 */

export function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) {
    return "—";
  }
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) {
      return "—";
    }
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(d);
  } catch {
    return isoString;
  }
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) {
    return "—";
  }
  return `${ms.toFixed(1)} ms`;
}

export function formatPort(port: number | null | undefined): string {
  if (port === null || port === undefined) {
    return "—";
  }
  return String(port);
}
