import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HostsPage } from "../src/pages/HostsPage";
import { HostDetailPage } from "../src/pages/HostDetailPage";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiConfigProvider } from "../src/providers/ApiConfigProvider";
import { ThemeProvider } from "../src/providers/ThemeProvider";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { HostResponse, HostHistoryResponse } from "../src/api/types";

const mockHosts: HostResponse[] = [
  {
    id: 1,
    address: "192.168.1.50",
    name: "Primary Gateway",
    enabled: true,
    created_at: "2026-10-04T08:00:00Z",
    updated_at: "2026-10-04T08:00:00Z",
  },
  {
    id: 2,
    address: "192.168.1.51",
    name: "Backup Switch",
    enabled: false,
    created_at: "2026-10-04T08:05:00Z",
    updated_at: "2026-10-04T08:05:00Z",
  },
];

const mockHostHistory: HostHistoryResponse = {
  host_id: 1,
  address: "192.168.1.50",
  name: "Primary Gateway",
  enabled: true,
  scans: [
    {
      scan_id: 201,
      status: "AVAILABLE",
      response_time_ms: 15.4,
      started_at: "2026-10-04T09:00:00Z",
      port_count: 2,
      event_count: 0,
      alert_count: 0,
    },
  ],
};

function renderHosts(initialUrl = "/hosts") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ApiConfigProvider>
        <ThemeProvider>
          <MemoryRouter initialEntries={[initialUrl]}>
            <Routes>
              <Route path="/hosts" element={<HostsPage />} />
              <Route path="/hosts/:target" element={<HostDetailPage />} />
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </ApiConfigProvider>
    </QueryClientProvider>
  );
}

describe("Hosts Page & Host Details", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders hosts list and filters by server-side query 'q'", async () => {
    const user = userEvent.setup();
    let requestedUrl = "";

    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      requestedUrl = url.toString();
      return new Response(
        JSON.stringify({
          items: mockHosts,
          count: mockHosts.length,
          limit: 20,
          offset: 0,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      );
    });

    renderHosts("/hosts");

    expect(await screen.findByText("Primary Gateway")).toBeInTheDocument();
    expect(screen.getByText("192.168.1.50")).toBeInTheDocument();

    // Type in search query input
    const searchInput = screen.getByLabelText("Search hosts");
    await user.type(searchInput, "Gateway");
    const searchBtn = screen.getByLabelText("Submit search");
    await user.click(searchBtn);

    await waitFor(() => {
      expect(requestedUrl).toContain("q=Gateway");
    });
  });

  it("renders host details and scan history", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/hosts/192.168.1.50/history")) {
        return new Response(JSON.stringify(mockHostHistory), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(
        JSON.stringify({
          items: mockHosts,
          count: mockHosts.length,
          limit: 20,
          offset: 0,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    });

    renderHosts("/hosts/192.168.1.50");

    expect(await screen.findByText("192.168.1.50")).toBeInTheDocument();
    expect(screen.getByText(/Primary Gateway/)).toBeInTheDocument();
    expect(screen.getByText("Monitoring Scan History")).toBeInTheDocument();
    expect(screen.getByText("#201")).toBeInTheDocument();
  });
});
