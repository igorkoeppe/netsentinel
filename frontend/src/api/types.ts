/**
 * NetSentinel REST API TypeScript Contract Types
 * Strictly aligned with backend Pydantic v2 schemas.
 */

export interface PaginatedResponse<T> {
  items: T[];
  count: number;
  limit: number;
  offset: number;
}

export interface ErrorDetail {
  code: string;
  message: string;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

/* ==========================================================================
   Health
   ========================================================================== */

export interface HealthLiveResponse {
  status: string;
  service: string;
  version: string;
}

export interface HealthReadyResponse {
  status: "ready" | "unavailable";
  database: "available" | "unavailable" | "not_configured";
}

/* ==========================================================================
   Hosts
   ========================================================================== */

export interface HostResponse {
  id: number;
  name: string | null;
  address: string;
  enabled: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface ScanHistoryItem {
  scan_id: number;
  started_at: string;
  status: string;
  response_time_ms: number | null;
  port_count: number;
  event_count: number;
  alert_count: number;
}

export interface HostHistoryResponse {
  host_id: number;
  address: string;
  name: string | null;
  enabled: boolean;
  scans: ScanHistoryItem[];
}

/* ==========================================================================
   Scans
   ========================================================================== */

export interface PortResultResponse {
  port: number;
  status: string;
  response_time_ms: number | null;
}

export interface MonitoringEventResponse {
  event_type: string;
  port: number | null;
  previous_state: string | null;
  current_state: string | null;
  created_at: string;
}

export interface ScanAlertResponse {
  id: number;
  alert_type: string;
  severity: string;
  message: string;
  port: number | null;
  created_at: string;
  monitoring_event_id: number | null;
}

export interface ScanDetailsResponse {
  id: number;
  target: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
  response_time_ms: number | null;
  ports: PortResultResponse[];
  events: MonitoringEventResponse[];
  alerts: ScanAlertResponse[];
}

export interface ScanSummaryResponse {
  id: number;
  target: string;
  status: string;
  response_time_ms: number | null;
  started_at: string;
  finished_at: string | null;
}

/* ==========================================================================
   Alerts & Triage
   ========================================================================== */

export type AlertStatus = "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
export type AlertSeverity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface AlertResponse {
  id: number;
  target: string;
  port: number | null;
  alert_type: string;
  severity: AlertSeverity;
  status: AlertStatus;
  message: string;
  created_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  scan_id: number | null;
  monitoring_event_id: number | null;
}

export interface AlertSummaryResponse {
  total: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
}

export interface NotificationDeliveryResponse {
  id: number;
  alert_id: number;
  channel: string;
  success: boolean;
  attempts: number;
  error: string | null;
  created_at: string;
}

/* ==========================================================================
   Dashboard Overview
   ========================================================================== */

export interface HostsSummary {
  total: number;
  enabled: number;
  disabled: number;
}

export interface ScansSummary {
  total: number;
  last_scan_at: string | null;
}

export interface AlertsSummary {
  total: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
}

export interface DashboardSummaryResponse {
  hosts: HostsSummary;
  scans: ScansSummary;
  alerts: AlertsSummary;
}
