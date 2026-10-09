import { ApiClient } from "./client";
import {
  PaginatedResponse,
  ScanDetailsResponse,
  ScanSummaryResponse,
} from "./types";

export interface ListScansParams {
  limit?: number;
  offset?: number;
  target?: string;
}

export function listScans(
  client: ApiClient,
  params: ListScansParams = {}
): Promise<PaginatedResponse<ScanSummaryResponse>> {
  return client.get<PaginatedResponse<ScanSummaryResponse>>("/scans", {
    params: {
      limit: params.limit,
      offset: params.offset,
      target: params.target,
    },
  });
}

export function getScan(client: ApiClient, scanId: number): Promise<ScanDetailsResponse> {
  return client.get<ScanDetailsResponse>(`/scans/${encodeURIComponent(scanId)}`);
}
