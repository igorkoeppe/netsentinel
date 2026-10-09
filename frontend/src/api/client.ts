import { ErrorResponse } from "./types";

export class ApiClientError extends Error {
  public status: number;
  public code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
  }
}

export { ApiClientError as ApiError };

export interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | null | undefined>;
}

export class ApiClient {
  private getBaseUrl: () => string;
  private getApiKey: () => string | null;

  constructor(
    getBaseUrl: () => string = () => "/api/v1",
    getApiKey: () => string | null = () => null
  ) {
    this.getBaseUrl = getBaseUrl;
    this.getApiKey = getApiKey;
  }

  public async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { params, headers: customHeaders, ...fetchOptions } = options;

    let baseUrl = this.getBaseUrl().trim();
    if (!baseUrl) {
      baseUrl = "/api/v1";
    }
    // Remove trailing slash
    baseUrl = baseUrl.replace(/\/+$/, "");

    // Ensure leading slash on path
    const normalizedPath = path.startsWith("/") ? path : `/${path}`;
    let url = `${baseUrl}${normalizedPath}`;

    // Append query parameters safely
    if (params) {
      const searchParams = new URLSearchParams();
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null && value !== "") {
          searchParams.append(key, String(value));
        }
      }
      const qs = searchParams.toString();
      if (qs) {
        url += (url.includes("?") ? "&" : "?") + qs;
      }
    }

    const headers = new Headers(customHeaders);
    headers.set("Accept", "application/json");

    if (fetchOptions.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    // Attach X-API-Key header if configured (NEVER in query parameters)
    const apiKey = this.getApiKey();
    if (apiKey && apiKey.trim()) {
      headers.set("X-API-Key", apiKey.trim());
    }

    let response: Response;
    try {
      response = await fetch(url, {
        ...fetchOptions,
        headers,
      });
    } catch {
      throw new ApiClientError(0, "NETWORK_ERROR", "Unable to connect to NetSentinel server.");
    }

    // Parse JSON envelope or handle errors
    let data: unknown = null;
    const contentType = response.headers.get("Content-Type") || "";
    if (contentType.includes("application/json")) {
      try {
        data = await response.json();
      } catch {
        data = null;
      }
    }

    if (!response.ok) {
      // 401 Unauthorized handling
      if (response.status === 401) {
        throw new ApiClientError(
          401,
          "UNAUTHORIZED",
          "Authentication required or API key invalid."
        );
      }

      // Check standard error envelope
      if (
        data &&
        typeof data === "object" &&
        "error" in data &&
        data.error &&
        typeof data.error === "object"
      ) {
        const err = data as ErrorResponse;
        const code = err.error.code || `HTTP_${response.status}`;
        let message = err.error.message || `Request failed with status ${response.status}`;

        if (response.status === 503 && code === "MUTATIONS_DISABLED") {
          message = "Remote mutations are disabled on the server (API_KEY is unconfigured).";
        }

        throw new ApiClientError(response.status, code, message);
      }

      // Fallback message
      throw new ApiClientError(
        response.status,
        `HTTP_${response.status}`,
        `Request failed with status ${response.status}.`
      );
    }

    return data as T;
  }

  public get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  public post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
  }
}
