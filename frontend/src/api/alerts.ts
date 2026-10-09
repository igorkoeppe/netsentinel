import { ApiClient } from "./client";
import {
  AlertResponse,
  AlertSeverity,
  AlertStatus,
  AlertSummaryResponse,
  NotificationDeliveryResponse,
  PaginatedResponse,
} from "./types";

export interface ListAlertsParams {
  status?: AlertStatus;
  severity?: AlertSeverity;
  type?: string;
  target?: string;
  limit?: number;
  offset?: number;
}

export function listAlerts(
  client: ApiClient,
  params: ListAlertsParams = {}
): Promise<PaginatedResponse<AlertResponse>> {
  return client.get<PaginatedResponse<AlertResponse>>("/alerts", {
    params: {
      status: params.status,
      severity: params.severity,
      type: params.type,
      target: params.target,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export function getAlertSummary(client: ApiClient): Promise<AlertSummaryResponse> {
  return client.get<AlertSummaryResponse>("/alerts/summary");
}

export function getAlert(client: ApiClient, alertId: number): Promise<AlertResponse> {
  return client.get<AlertResponse>(`/alerts/${encodeURIComponent(alertId)}`);
}

export function getAlertDeliveries(
  client: ApiClient,
  alertId: number
): Promise<NotificationDeliveryResponse[]> {
  return client.get<NotificationDeliveryResponse[]>(
    `/alerts/${encodeURIComponent(alertId)}/deliveries`
  );
}

export function acknowledgeAlert(client: ApiClient, alertId: number): Promise<AlertResponse> {
  return client.post<AlertResponse>(
    `/alerts/${encodeURIComponent(alertId)}/acknowledge`
  );
}

export function resolveAlert(client: ApiClient, alertId: number): Promise<AlertResponse> {
  return client.post<AlertResponse>(`/alerts/${encodeURIComponent(alertId)}/resolve`);
}
