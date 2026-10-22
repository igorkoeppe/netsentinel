import { ApiClient } from "./client";
import {
  PaginatedResponse,
  ScheduleCreateRequest,
  ScheduleResponse,
  ScheduleUpdateRequest,
} from "./types";

export interface ListSchedulesParams {
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function listSchedules(
  client: ApiClient,
  params: ListSchedulesParams = {}
): Promise<PaginatedResponse<ScheduleResponse>> {
  return client.get<PaginatedResponse<ScheduleResponse>>("/schedules", {
    params: {
      limit: params.limit,
      offset: params.offset,
      enabled: params.enabled,
    },
  });
}

export function createSchedule(
  client: ApiClient,
  body: ScheduleCreateRequest
): Promise<ScheduleResponse> {
  return client.post<ScheduleResponse>("/schedules", body);
}

export function updateSchedule(
  client: ApiClient,
  scheduleId: number,
  body: ScheduleUpdateRequest
): Promise<ScheduleResponse> {
  return client.patch<ScheduleResponse>(
    `/schedules/${encodeURIComponent(scheduleId)}`,
    body
  );
}

/**
 * Parse a comma-separated port list ("22, 80,443") into numbers.
 * Returns null when any item is not a valid TCP port.
 */
export function parsePortList(value: string): number[] | null {
  const items = value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "");
  if (items.length === 0) return null;
  const ports: number[] = [];
  for (const item of items) {
    if (!/^\d+$/.test(item)) return null;
    const port = Number(item);
    if (port < 1 || port > 65535) return null;
    ports.push(port);
  }
  return ports;
}
