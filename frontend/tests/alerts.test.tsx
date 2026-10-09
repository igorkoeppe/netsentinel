import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AlertsPage } from "../src/pages/AlertsPage";
import { AlertDetailPage } from "../src/pages/AlertDetailPage";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiConfigProvider } from "../src/providers/ApiConfigProvider";
import { ThemeProvider } from "../src/providers/ThemeProvider";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { AlertResponse, NotificationDeliveryResponse } from "../src/api/types";

const mockAlerts: AlertResponse[] = [
  {
    id: 1,
    target: "192.168.1.10",
    port: 22,
    alert_type: "NEW_OPEN_PORT",
    severity: "HIGH",
    status: "OPEN",
    message: "New open port 22 detected",
    created_at: "2026-10-04T10:00:00Z",
    acknowledged_at: null,
    resolved_at: null,
    scan_id: 101,
    monitoring_event_id: null,
  },
  {
    id: 2,
    target: "192.168.1.20",
    port: 80,
    alert_type: "PORT_CLOSED",
    severity: "LOW",
    status: "ACKNOWLEDGED",
    message: "Port 80 closed",
    created_at: "2026-10-04T10:05:00Z",
    acknowledged_at: "2026-10-04T10:10:00Z",
    resolved_at: null,
    scan_id: 102,
    monitoring_event_id: null,
  },
];

const mockDeliveries: NotificationDeliveryResponse[] = [
  {
    id: 1,
    alert_id: 1,
    channel: "webhook",
    success: true,
    attempts: 1,
    error: null,
    created_at: "2026-10-04T10:00:05Z",
  },
  {
    id: 2,
    alert_id: 1,
    channel: "webhook",
    success: false,
    attempts: 3,
    error: "Connection refused",
    created_at: "2026-10-04T10:00:10Z",
  },
];

function renderAlertsPage(initialUrl = "/alerts") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ApiConfigProvider>
        <ThemeProvider>
          <MemoryRouter initialEntries={[initialUrl]}>
            <Routes>
              <Route path="/alerts" element={<AlertsPage />} />
              <Route path="/alerts/:alertId" element={<AlertDetailPage />} />
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </ApiConfigProvider>
    </QueryClientProvider>
  );
}

describe("Alerts Page & Triage Flows", () => {
  it("shows delivery errors and lets the operator retry", async () => {
    const user = userEvent.setup();
    let failDeliveries = true;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const isDelivery = url.toString().includes("/deliveries");
      const failed = isDelivery && failDeliveries;
      const payload = failed
        ? { error: { code: "INTERNAL_SERVER_ERROR", message: "Delivery history unavailable." } }
        : isDelivery ? { items: mockDeliveries, count: 2, limit: 20, offset: 0 } : mockAlerts[0];
      return new Response(JSON.stringify(payload), {
        status: failed ? 500 : 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    renderAlertsPage("/alerts/1");
    expect(await screen.findByText("Unable to load delivery history")).toBeInTheDocument();
    expect(screen.queryByText("No deliveries recorded")).toBeNull();
    failDeliveries = false;
    await user.click(screen.getByText("Retry delivery history"));
    expect(await screen.findByText("Connection refused")).toBeInTheDocument();
    expect(screen.queryByText("Unable to load delivery history")).toBeNull();
  });

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders alerts list and handles URL filter synchronization", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/alerts?")) {
        return new Response(
          JSON.stringify({
            items: mockAlerts,
            count: mockAlerts.length,
            limit: 20,
            offset: 0,
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        );
      }
      return new Response(JSON.stringify({ items: [], count: 0, limit: 20, offset: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    renderAlertsPage("/alerts?status=OPEN&severity=HIGH");

    // Check that fetch was called with the filter params from URL
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
      const calledUrl = fetchSpy.mock.calls[0][0].toString();
      expect(calledUrl).toContain("status=OPEN");
      expect(calledUrl).toContain("severity=HIGH");
    });

    // Check items rendered
    expect(await screen.findByText("192.168.1.10")).toBeInTheDocument();
    expect(screen.getByText("NEW_OPEN_PORT")).toBeInTheDocument();
  });

  it("handles acknowledge mutation with modal confirmation", async () => {
    const user = userEvent.setup();

    let postCalled = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      const urlStr = url.toString();
      if (urlStr.includes("/deliveries")) {
        return new Response(
          JSON.stringify({
            items: mockDeliveries,
            count: mockDeliveries.length,
            limit: 20,
            offset: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (urlStr.includes("/alerts/1/acknowledge") && init?.method === "POST") {
        postCalled = true;
        return new Response(
          JSON.stringify({
            ...mockAlerts[0],
            status: "ACKNOWLEDGED",
            acknowledged_at: "2026-10-04T10:15:00Z",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (urlStr.includes("/alerts/1")) {
        return new Response(JSON.stringify(mockAlerts[0]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ items: [], count: 0, limit: 20, offset: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    renderAlertsPage("/alerts/1");

    // Wait for alert details to load
    expect(await screen.findByText("Alert #1")).toBeInTheDocument();

    // Find and click Acknowledge button
    const ackBtn = screen.getByRole("button", { name: /acknowledge/i });
    await user.click(ackBtn);

    // Confirmation modal should appear
    expect(await screen.findByText("Acknowledge Alert #1")).toBeInTheDocument();

    // Confirm in modal
    const confirmBtn = screen.getByRole("button", { name: "Confirm" });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(postCalled).toBe(true);
    });
  });

  it("handles HTTP 409 conflict gracefully during mutation", async () => {
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      const urlStr = url.toString();
      if (urlStr.includes("/deliveries")) {
        return new Response(
          JSON.stringify({
            items: [],
            count: 0,
            limit: 20,
            offset: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (urlStr.includes("/alerts/1/acknowledge") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            error: {
              code: "CONFLICT",
              message: "Alert state has already changed",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } }
        );
      }
      if (urlStr.includes("/alerts/1")) {
        return new Response(JSON.stringify(mockAlerts[0]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ items: [], count: 0, limit: 20, offset: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    renderAlertsPage("/alerts/1");

    expect(await screen.findByText("Alert #1")).toBeInTheDocument();

    const ackBtn = screen.getByRole("button", { name: /acknowledge/i });
    await user.click(ackBtn);

    const confirmBtn = await screen.findByRole("button", { name: "Confirm" });
    await user.click(confirmBtn);

    // Expect conflict message to appear
    expect(
      await screen.findByText("Alert state changed. Refreshing data.")
    ).toBeInTheDocument();
  });

  it("renders delivery history and empty state correctly without leaking webhook URL", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/deliveries")) {
        return new Response(
          JSON.stringify({
            items: mockDeliveries,
            count: mockDeliveries.length,
            limit: 20,
            offset: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (urlStr.includes("/alerts/1")) {
        return new Response(JSON.stringify(mockAlerts[0]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ items: [], count: 0, limit: 20, offset: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    renderAlertsPage("/alerts/1");

    expect(await screen.findByText("Notification Delivery Audit")).toBeInTheDocument();
    // Delivery items rendered
    expect(screen.getByText("Connection refused")).toBeInTheDocument();
    expect(screen.getByText("SUCCESS")).toBeInTheDocument();
    expect(screen.getByText("FAILED")).toBeInTheDocument();

    // Confirm no webhook URL appears anywhere
    expect(screen.queryByText(/https?:\/\//i)).toBeNull();
  });

  it("handles 404 alert details gracefully", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/alerts/999")) {
        return new Response(
          JSON.stringify({
            error: { code: "ALERT_NOT_FOUND", message: "Alert 999 not found." },
          }),
          { status: 404, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    renderAlertsPage("/alerts/999");

    expect(await screen.findByText("Alert Not Found")).toBeInTheDocument();
    expect(screen.getByText("Alert #999 not found.")).toBeInTheDocument();
  });

  it("handles 401 unauthorized alert details gracefully", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/alerts/473")) {
        return new Response(
          JSON.stringify({
            error: { code: "UNAUTHORIZED", message: "Authentication required." },
          }),
          { status: 401, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    renderAlertsPage("/alerts/473");

    expect(await screen.findByText("Authentication required")).toBeInTheDocument();
    expect(screen.queryByText("Alert Not Found")).toBeNull();
  });

  it("handles 500 internal server error gracefully without showing 'Alert Not Found'", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/alerts/473")) {
        return new Response(
          JSON.stringify({
            error: {
              code: "INTERNAL_SERVER_ERROR",
              message: "An unexpected internal error occurred.",
            },
          }),
          { status: 500, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    renderAlertsPage("/alerts/473");

    expect(await screen.findByText("Unable to load alert")).toBeInTheDocument();
    expect(screen.getByText("An unexpected internal error occurred.")).toBeInTheDocument();
    // Must NOT show "Alert Not Found"
    expect(screen.queryByText("Alert Not Found")).toBeNull();
  });
});
