import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { HealthIndicator } from "../src/components/HealthIndicator";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiConfigProvider } from "../src/providers/ApiConfigProvider";

function renderHealth() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ApiConfigProvider>
        <HealthIndicator />
      </ApiConfigProvider>
    </QueryClientProvider>
  );
}

describe("Health Indicator", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows API: Online and Database: Ready when both are healthy", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/health/live")) {
        return new Response(JSON.stringify({ status: "ok", service: "netsentinel", version: "0.8.0" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (urlStr.includes("/health/ready")) {
        return new Response(
          JSON.stringify({ status: "ready", database: "available" }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response(JSON.stringify({}), { status: 404 });
    });

    renderHealth();

    expect(await screen.findByText("Online")).toBeInTheDocument();
    expect(await screen.findByText("Ready")).toBeInTheDocument();
  });

  it("distinguishes when Database is unavailable (503 on ready)", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/health/live")) {
        return new Response(JSON.stringify({ status: "ok", service: "netsentinel", version: "0.8.0" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (urlStr.includes("/health/ready")) {
        return new Response(
          JSON.stringify({
            status: "unavailable",
            database: "unavailable",
          }),
          { status: 503, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response(JSON.stringify({}), { status: 404 });
    });

    renderHealth();

    expect(await screen.findByText("Online")).toBeInTheDocument();
    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    // Ensure raw exception is NOT leaked
    expect(screen.queryByText(/Traceback/i)).toBeNull();
  });
});
