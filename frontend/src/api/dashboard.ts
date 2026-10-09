import { ApiClient } from "./client";
import { DashboardSummaryResponse } from "./types";

export function getDashboardSummary(client: ApiClient): Promise<DashboardSummaryResponse> {
  return client.get<DashboardSummaryResponse>("/dashboard/summary");
}
