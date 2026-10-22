import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SchedulesPage } from "../src/pages/SchedulesPage";
import { parsePortList } from "../src/api/schedules";
import type { ScheduleResponse } from "../src/api/types";
import { renderWithProviders } from "./test-utils";

const baseSchedule: ScheduleResponse = {
  id: 1,
  host_id: 10,
  target: "192.168.1.50",
  name: "Primary Gateway",
  ports: [22, 443],
  interval_seconds: 300,
  enabled: true,
  next_run_at: "2026-10-22T12:05:00Z",
  last_run_at: "2026-10-22T12:00:00Z",
  last_scan_id: 77,
  last_error: null,
  created_at: "2026-10-22T11:00:00Z",
  updated_at: null,
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function page(items: ScheduleResponse[]) {
  return { items, count: items.length, limit: 100, offset: 0 };
}

describe("parsePortList", () => {
  it("parses comma-separated ports", () => {
    expect(parsePortList("22, 80,443")).toEqual([22, 80, 443]);
  });

  it("rejects invalid input", () => {
    expect(parsePortList("")).toBeNull();
    expect(parsePortList("22,abc")).toBeNull();
    expect(parsePortList("0")).toBeNull();
    expect(parsePortList("70000")).toBeNull();
    expect(parsePortList("22-80")).toBeNull();
  });
});

describe("Schedules Page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("lists schedules with interval, ports and last error", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      json(
        page([
          baseSchedule,
          {
            ...baseSchedule,
            id: 2,
            target: "10.0.0.9",
            name: null,
            interval_seconds: 3600,
            enabled: false,
            last_error: "OSError: network is unreachable",
          },
        ])
      )
    );

    renderWithProviders(<SchedulesPage />, { initialEntries: ["/schedules"] });

    expect(await screen.findByText("192.168.1.50")).toBeInTheDocument();
    expect(screen.getAllByText("22, 443")).toHaveLength(2);
    expect(screen.getByText("5 min")).toBeInTheDocument();
    expect(screen.getByText("1 h")).toBeInTheDocument();
    expect(screen.getByText("OSError: network is unreachable")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Enable schedule for 10.0.0.9" })
    ).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(page([])));
    renderWithProviders(<SchedulesPage />, { initialEntries: ["/schedules"] });
    expect(await screen.findByText("No scan schedules")).toBeInTheDocument();
  });

  it("disables a schedule with PATCH", async () => {
    const user = userEvent.setup();
    let patchBody: unknown = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (url.toString().includes("/schedules/1") && init?.method === "PATCH") {
        patchBody = JSON.parse(String(init.body));
        return json({ ...baseSchedule, enabled: false });
      }
      return json(page([baseSchedule]));
    });

    renderWithProviders(<SchedulesPage />, { initialEntries: ["/schedules"] });
    await user.click(
      await screen.findByRole("button", { name: "Disable schedule for 192.168.1.50" })
    );

    await waitFor(() => expect(patchBody).toEqual({ enabled: false }));
    expect(
      await screen.findByText("Schedule for 192.168.1.50 disabled.")
    ).toBeInTheDocument();
  });

  it("creates a schedule from the form", async () => {
    const user = userEvent.setup();
    let postBody: unknown = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (url.toString().includes("/schedules") && init?.method === "POST") {
        postBody = JSON.parse(String(init.body));
        return json({ ...baseSchedule, id: 5, target: "10.0.0.1" }, 201);
      }
      return json(page([]));
    });

    renderWithProviders(<SchedulesPage />, { initialEntries: ["/schedules"] });
    await screen.findByText("No scan schedules");

    await user.type(screen.getByLabelText("Target"), "10.0.0.1");
    await user.type(screen.getByLabelText("TCP ports"), "22, 8080");
    const interval = screen.getByLabelText("Interval (seconds)");
    await user.clear(interval);
    await user.type(interval, "600");
    await user.click(screen.getByRole("button", { name: /add schedule/i }));

    await waitFor(() =>
      expect(postBody).toEqual({
        target: "10.0.0.1",
        ports: [22, 8080],
        interval_seconds: 600,
      })
    );
    expect(await screen.findByText("Schedule created for 10.0.0.1.")).toBeInTheDocument();
  });

  it("validates ports before calling the API", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => json(page([])));

    renderWithProviders(<SchedulesPage />, { initialEntries: ["/schedules"] });
    await screen.findByText("No scan schedules");

    await user.type(screen.getByLabelText("Target"), "10.0.0.1");
    await user.type(screen.getByLabelText("TCP ports"), "22,ssh");
    await user.click(screen.getByRole("button", { name: /add schedule/i }));

    expect(
      await screen.findByText(/comma-separated list of numbers/i)
    ).toBeInTheDocument();
    const posts = fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(0);
  });

  it("surfaces API errors such as a duplicate schedule", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
      if (init?.method === "POST") {
        return json(
          {
            error: {
              code: "SCHEDULE_EXISTS",
              message: "Host '10.0.0.1' already has a scan schedule.",
            },
          },
          409
        );
      }
      return json(page([]));
    });

    renderWithProviders(<SchedulesPage />, { initialEntries: ["/schedules"] });
    await screen.findByText("No scan schedules");
    await user.type(screen.getByLabelText("Target"), "10.0.0.1");
    await user.type(screen.getByLabelText("TCP ports"), "22");
    await user.click(screen.getByRole("button", { name: /add schedule/i }));

    expect(
      await screen.findByText("Host '10.0.0.1' already has a scan schedule.")
    ).toBeInTheDocument();
  });
});
