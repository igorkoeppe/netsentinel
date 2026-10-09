import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ScansPage } from "../src/pages/ScansPage";
import { ScanDetailPage } from "../src/pages/ScanDetailPage";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiConfigProvider } from "../src/providers/ApiConfigProvider";
import { ThemeProvider } from "../src/providers/ThemeProvider";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ScanSummaryResponse, ScanDetailsResponse } from "../src/api/types";

const mockScansList: ScanSummaryResponse[] = [
  {
    id: 501,
    target: "192.168.1.1",
    status: "AVAILABLE",
    response_time_ms: 12.3,
    started_at: "2026-10-04T10:00:00Z",
    finished_at: "2026-10-04T10:00:02Z",
  },
];

const mockScanDetail: ScanDetailsResponse = {
  id: 501,
  target: "192.168.1.1",
  status: "AVAILABLE",
  response_time_ms: 12.3,
  started_at: "2026-10-04T10:00:00Z",
  finished_at: "2026-10-04T10:00:02Z",
  ports: [
    { port: 80, status: "OPEN", response_time_ms: 5.2 },
    { port: 443, status: "CLOSED", response_time_ms: null },
  ],
  events: [
    {
      event_type: "PORT_OPEN",
      port: 80,
      previous_state: "CLOSED",
      current_state: "OPEN",
      created_at: "2026-10-04T10:00:01Z",
    },
  ],
  alerts: [
    {
      id: 1,
      port: 80,
      alert_type: "NEW_OPEN_PORT",
      severity: "HIGH",
      message: "Port 80 newly open",
      created_at: "2026-10-04T10:00:01Z",
      monitoring_event_id: null,
    },
  ],
};

function renderScans(initialUrl = "/scans") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ApiConfigProvider>
        <ThemeProvider>
          <MemoryRouter initialEntries={[initialUrl]}>
            <Routes>
              <Route path="/scans" element={<ScansPage />} />
              <Route path="/scans/:scanId" element={<ScanDetailPage />} />
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </ApiConfigProvider>
    </QueryClientProvider>
  );
}

describe("Scans Page & Scan Details", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders global scans list and filters by target", async () => {
    const user = userEvent.setup();
    let requestedUrl = "";

    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      requestedUrl = url.toString();
      return new Response(
        JSON.stringify({
          items: mockScansList,
          count: mockScansList.length,
          limit: 20,
          offset: 0,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      );
    });

    renderScans("/scans");

    expect(await screen.findByText("#501")).toBeInTheDocument();
    expect(screen.getByText("192.168.1.1")).toBeInTheDocument();

    const targetInput = screen.getByLabelText("Filter scans by target");
    await user.type(targetInput, "192.168.1.1");
    const filterBtn = screen.getByLabelText("Submit search");
    await user.click(filterBtn);

    await waitFor(() => {
      expect(requestedUrl).toContain("target=192.168.1.1");
    });
  });

  it("renders scan detail sections: Ports, Events, Security Alerts", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/scans/501")) {
        return new Response(JSON.stringify(mockScanDetail), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(
        JSON.stringify({
          items: mockScansList,
          count: mockScansList.length,
          limit: 20,
          offset: 0,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    });

    renderScans("/scans/501");

    expect(await screen.findByText("Scan #501")).toBeInTheDocument();

    // Ports section
    expect(screen.getByText("Probed Ports")).toBeInTheDocument();
    expect(screen.getAllByText("80").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("443")).toBeInTheDocument();

    // Events section
    expect(screen.getByText("Observed Monitoring Events")).toBeInTheDocument();
    expect(screen.getByText("PORT_OPEN")).toBeInTheDocument();

    // Security Alerts section
    expect(screen.getByText("Generated Security Alerts")).toBeInTheDocument();
    expect(screen.getByText("Port 80 newly open")).toBeInTheDocument();
  });
});
