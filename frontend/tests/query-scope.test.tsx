import { describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useQuery } from "@tanstack/react-query";
import { ApiConfigProvider } from "../src/providers/ApiConfigProvider";
import { QueryProvider } from "../src/providers/QueryProvider";
import { useApiConfig } from "../src/hooks/useApiConfig";

describe("Connection-scoped queries", () => {
  it("discards cached data when switching servers or clearing credentials", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      const key = new Headers(init?.headers).get("X-API-Key");
      return new Response(JSON.stringify({ source: `${url}:${key || "anonymous"}` }), {
        headers: { "Content-Type": "application/json" },
      });
    });
    function Consumer() {
      const { client, setBaseUrl, setApiKey, clearApiKey } = useApiConfig();
      const { data } = useQuery({
        queryKey: ["dashboard-summary"],
        queryFn: () => client.get<{ source: string }>("/summary"),
        refetchInterval: false,
      });
      return <>
        <span>{data?.source || "Loading"}</span>
        <button onClick={() => setBaseUrl("/server-b")}>Switch server</button>
        <button onClick={() => setApiKey("test-key")}>Authenticate</button>
        <button onClick={clearApiKey}>Clear credentials</button>
      </>;
    }
    try {
      render(<StrictMode><ApiConfigProvider><QueryProvider><Consumer /></QueryProvider></ApiConfigProvider></StrictMode>);
      expect(await screen.findByText("/api/v1/summary:anonymous")).toBeInTheDocument();
      await user.click(screen.getByText("Authenticate"));
      expect(await screen.findByText("/api/v1/summary:test-key")).toBeInTheDocument();
      await user.click(screen.getByText("Switch server"));
      expect(await screen.findByText("/server-b/summary:test-key")).toBeInTheDocument();
      await user.click(screen.getByText("Clear credentials"));
      expect(await screen.findByText("/server-b/summary:anonymous")).toBeInTheDocument();
      expect(screen.queryByText("/server-b/summary:test-key")).toBeNull();
      expect(fetchSpy.mock.calls.length).toBeGreaterThanOrEqual(4);
    } finally {
      fetchSpy.mockRestore();
    }
  });

  it("does not restore old data when an earlier connection finishes late", async () => {
    const user = userEvent.setup();
    let finishOld!: (value: Response) => void;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((url) => {
      if (url.toString().startsWith("/api/v1")) {
        return new Promise<Response>((resolve) => { finishOld = resolve; });
      }
      return Promise.resolve(new Response(JSON.stringify("new-server"), {
        headers: { "Content-Type": "application/json" },
      }));
    });
    function Consumer() {
      const { client, setBaseUrl } = useApiConfig();
      const { data } = useQuery({ queryKey: ["same-key"], queryFn: () => client.get<string>("/data") });
      return <><span>{data || "Loading"}</span><button onClick={() => setBaseUrl("/new")}>Switch</button></>;
    }
    try {
      render(<ApiConfigProvider><QueryProvider><Consumer /></QueryProvider></ApiConfigProvider>);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
      await user.click(screen.getByText("Switch"));
      expect(await screen.findByText("new-server")).toBeInTheDocument();
      await act(async () => {
        finishOld(new Response(JSON.stringify("old-server"), { headers: { "Content-Type": "application/json" } }));
      });
      await waitFor(() => expect(screen.queryByText("old-server")).toBeNull());
      expect(screen.getByText("new-server")).toBeInTheDocument();
    } finally {
      fetchSpy.mockRestore();
    }
  });
});
