import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { OverviewPage } from "../src/pages/OverviewPage";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiConfigProvider } from "../src/providers/ApiConfigProvider";
import { ThemeProvider } from "../src/providers/ThemeProvider";
import { MemoryRouter } from "react-router-dom";
import type { DashboardSummaryResponse } from "../src/api/types";

const mockSummary: DashboardSummaryResponse = {
  hosts: {
    total: 10,
    enabled: 8,
    disabled: 2,
  },
  scans: {
    total: 150,
    last_scan_at: "2026-10-04T10:00:00Z",
  },
  alerts: {
    total: 25,
    by_status: {
      OPEN: 5,
      ACKNOWLEDGED: 8,
      RESOLVED: 12,
    },
    by_severity: {
      INFO: 2,
      LOW: 3,
      MEDIUM: 5,
      HIGH: 10,
      CRITICAL: 5,
    },
  },
};

function renderOverview() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ApiConfigProvider>
        <ThemeProvider>
          <MemoryRouter initialEntries={["/"]}>
            <OverviewPage />
          </MemoryRouter>
        </ThemeProvider>
      </ApiConfigProvider>
    </QueryClientProvider>
  );
}

describe("Dashboard Overview Page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders metric cards and accessible chart representations", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/dashboard/summary")) {
        return new Response(JSON.stringify(mockSummary), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(
        JSON.stringify({ items: [], count: 0, limit: 5, offset: 0 }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    });

    renderOverview();

    // Metric cards
    expect(await screen.findByText("Monitored Hosts")).toBeInTheDocument();
    expect(screen.getAllByText("10").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("8 active")).toBeInTheDocument();

    expect(screen.getByText("Open Alerts")).toBeInTheDocument();
    expect(screen.getAllByText("5").length).toBeGreaterThanOrEqual(1); // open alerts

    expect(screen.getByText("High / Critical")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument(); // 10 high + 5 critical

    expect(screen.getByText("Total Scans")).toBeInTheDocument();
    expect(screen.getByText("150")).toBeInTheDocument();

    // Accessible text representations for charts
    expect(screen.getByText("Alerts by Status")).toBeInTheDocument();
    expect(screen.getByText("OPEN")).toBeInTheDocument();
    expect(screen.getByText("ACKNOWLEDGED")).toBeInTheDocument();
    expect(screen.getByText("RESOLVED")).toBeInTheDocument();

    expect(screen.getByText("Alerts by Severity")).toBeInTheDocument();
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
  });
});
