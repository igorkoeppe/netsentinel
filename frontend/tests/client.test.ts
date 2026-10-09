import { describe, it, expect, vi, beforeEach } from "vitest";
import { ApiClient, ApiError } from "../src/api/client";

describe("ApiClient", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends X-API-Key header when API key is provided", async () => {
    let capturedHeaders: HeadersInit | undefined;
    let capturedUrl: string | undefined;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      capturedUrl = url.toString();
      capturedHeaders = init?.headers;
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const client = new ApiClient(
      () => "/api/v1",
      () => "secret-test-token"
    );

    await client.get("/alerts");

    expect(capturedUrl).toBe("/api/v1/alerts");
    expect(capturedHeaders).toBeDefined();
    const headers = new Headers(capturedHeaders);
    expect(headers.get("X-API-Key")).toBe("secret-test-token");
    // Ensure key is NOT in query string
    expect(capturedUrl).not.toContain("secret-test-token");
    expect(capturedUrl).not.toContain("api_key");
  });

  it("does not send X-API-Key when key is null or empty", async () => {
    let capturedHeaders: HeadersInit | undefined;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (_, init) => {
      capturedHeaders = init?.headers;
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    });

    const client = new ApiClient(
      () => "/api/v1",
      () => null
    );

    await client.get("/health/live");

    const headers = new Headers(capturedHeaders);
    expect(headers.get("X-API-Key")).toBeNull();
  });

  it("handles 401 Unauthorized with descriptive message", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({
          error: {
            code: "UNAUTHORIZED",
            message: "Missing or invalid API key",
          },
        }),
        {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }
      );
    });

    const client = new ApiClient(
      () => "/api/v1",
      () => "bad-key"
    );

    await expect(client.get("/alerts")).rejects.toThrow(
      "Authentication required or API key invalid."
    );
  });

  it("handles 503 MUTATIONS_DISABLED with dedicated message", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({
          error: {
            code: "MUTATIONS_DISABLED",
            message: "Remote mutations are disabled",
          },
        }),
        {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }
      );
    });

    const client = new ApiClient(
      () => "/api/v1",
      () => "test-key"
    );

    await expect(client.post("/alerts/1/acknowledge")).rejects.toThrow(
      "Remote mutations are disabled on the server"
    );
  });

  it("parses structured error envelope from API", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({
          error: {
            code: "ALERT_NOT_FOUND",
            message: "Alert with ID 999 does not exist",
          },
        }),
        {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }
      );
    });

    const client = new ApiClient(
      () => "/api/v1",
      () => null
    );

    try {
      await client.get("/alerts/999");
      expect.fail("Expected ApiError to be thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(404);
      expect(apiErr.code).toBe("ALERT_NOT_FOUND");
      expect(apiErr.message).toBe("Alert with ID 999 does not exist");
    }
  });
});
