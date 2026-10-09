import { ApiClient } from "./client";
import { HostHistoryResponse, HostResponse, PaginatedResponse } from "./types";

export interface ListHostsParams {
  limit?: number;
  offset?: number;
  enabled?: boolean;
  q?: string;
}

export function listHosts(
  client: ApiClient,
  params: ListHostsParams = {}
): Promise<PaginatedResponse<HostResponse>> {
  return client.get<PaginatedResponse<HostResponse>>("/hosts", {
    params: {
      limit: params.limit,
      offset: params.offset,
      enabled: params.enabled,
      q: params.q,
    },
  });
}

export function getHostHistory(
  client: ApiClient,
  target: string,
  limit: number = 20
): Promise<HostHistoryResponse> {
  return client.get<HostHistoryResponse>(
    `/hosts/${encodeURIComponent(target)}/history`,
    {
      params: { limit },
    }
  );
}
