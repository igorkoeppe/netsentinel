import { ApiClient } from "./client";
import { HealthLiveResponse, HealthReadyResponse } from "./types";

export function getHealthLive(client: ApiClient): Promise<HealthLiveResponse> {
  return client.get<HealthLiveResponse>("/health/live");
}

export function getHealthReady(client: ApiClient): Promise<HealthReadyResponse> {
  return client.get<HealthReadyResponse>("/health/ready");
}
