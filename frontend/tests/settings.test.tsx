import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SettingsPage } from "../src/pages/SettingsPage";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiConfigProvider } from "../src/providers/ApiConfigProvider";
import { ThemeProvider } from "../src/providers/ThemeProvider";
import { MemoryRouter } from "react-router-dom";

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ApiConfigProvider>
        <ThemeProvider>
          <MemoryRouter initialEntries={["/settings"]}>
            <SettingsPage />
          </MemoryRouter>
        </ThemeProvider>
      </ApiConfigProvider>
    </QueryClientProvider>
  );
}

describe("Settings Page", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("toggles API key visibility securely", async () => {
    const user = userEvent.setup();
    renderSettings();

    const keyInput = screen.getByLabelText("API Key");
    expect(keyInput).toHaveAttribute("type", "password");

    await user.type(keyInput, "my-secret-key");

    // Toggle reveal button
    const revealBtn = screen.getByLabelText(/Show API Key/i);
    await user.click(revealBtn);
    expect(keyInput).toHaveAttribute("type", "text");

    // Toggle hide button
    const hideBtn = screen.getByLabelText(/Hide API Key/i);
    await user.click(hideBtn);
    expect(keyInput).toHaveAttribute("type", "password");
  });

  it("handles test connection successfully", async () => {
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const urlStr = url.toString();
      if (urlStr.includes("/health/live")) {
        return new Response(JSON.stringify({ status: "ok", service: "netsentinel", version: "0.8.0" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(
        JSON.stringify({ items: [], count: 0, limit: 1, offset: 0 }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    });

    renderSettings();

    const testBtn = screen.getByRole("button", { name: /test connection/i });
    await user.click(testBtn);

    expect(
      await screen.findByText(/Connected successfully to NetSentinel/i)
    ).toBeInTheDocument();
  });

  it("updates polling interval and persists in localStorage", async () => {
    const user = userEvent.setup();
    renderSettings();

    const pollSelect = screen.getByLabelText(/Select polling interval/i);
    expect(pollSelect).toHaveValue("10000");

    await user.selectOptions(pollSelect, "30000");
    expect(pollSelect).toHaveValue("30000");
    expect(localStorage.getItem("netsentinel_poll_interval")).toBe("30000");
  });
});
