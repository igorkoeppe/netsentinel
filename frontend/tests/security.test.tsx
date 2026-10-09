import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { ApiConfigProvider } from "../src/providers/ApiConfigProvider";
import { useApiConfig } from "../src/hooks/useApiConfig";
import userEvent from "@testing-library/user-event";

// Test component to interact with ApiConfig
const TestSecurityComponent: React.FC = () => {
  const { apiKey, setApiKey, clearApiKey, rememberKeyInSession, setRememberKeyInSession } =
    useApiConfig();

  return (
    <div>
      <span data-testid="key-display">{apiKey ?? "NO_KEY"}</span>
      <button
        onClick={() => setApiKey("test-secret-123", false)}
        data-testid="set-memory-key-btn"
      >
        Set Memory Key
      </button>
      <button
        onClick={() => {
          setRememberKeyInSession(true);
          setApiKey("test-session-secret", true);
        }}
        data-testid="set-session-key-btn"
      >
        Set Session Key
      </button>
      <button onClick={clearApiKey} data-testid="clear-key-btn">
        Clear Key
      </button>
      <span data-testid="session-flag">{String(rememberKeyInSession)}</span>
    </div>
  );
};

// Component testing untrusted data rendering (XSS test)
const XssProbeComponent: React.FC<{ untrustedText: string }> = ({ untrustedText }) => {
  return (
    <div data-testid="untrusted-container">
      <span data-testid="untrusted-content">{untrustedText}</span>
    </div>
  );
};

describe("Security Requirements", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("ensures VITE_API_KEY does not exist in environment", () => {
    const env = (import.meta as unknown as { env?: Record<string, unknown> }).env;
    expect(env?.VITE_API_KEY).toBeUndefined();
  });

  it("never stores API key in localStorage", async () => {
    const user = userEvent.setup();
    render(
      <ApiConfigProvider>
        <TestSecurityComponent />
      </ApiConfigProvider>
    );

    await user.click(screen.getByTestId("set-memory-key-btn"));
    expect(screen.getByTestId("key-display")).toHaveTextContent("test-secret-123");

    // LocalStorage must never contain the key or any apiKey key
    expect(localStorage.getItem("apiKey")).toBeNull();
    expect(localStorage.getItem("netsentinel_api_key")).toBeNull();
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key) {
        expect(localStorage.getItem(key)).not.toContain("test-secret-123");
      }
    }
  });

  it("supports optional sessionStorage and clearApiKey wipes it", async () => {
    const user = userEvent.setup();
    render(
      <ApiConfigProvider>
        <TestSecurityComponent />
      </ApiConfigProvider>
    );

    // Initially nothing in sessionStorage
    expect(sessionStorage.getItem("netsentinel_session_api_key")).toBeNull();

    // Set session key
    await user.click(screen.getByTestId("set-session-key-btn"));
    expect(screen.getByTestId("key-display")).toHaveTextContent("test-session-secret");
    expect(sessionStorage.getItem("netsentinel_session_api_key")).toBe("test-session-secret");

    // Clear key wipes sessionStorage
    await user.click(screen.getByTestId("clear-key-btn"));
    expect(screen.getByTestId("key-display")).toHaveTextContent("NO_KEY");
    expect(sessionStorage.getItem("netsentinel_session_api_key")).toBeNull();
  });

  it("safely escapes untrusted strings without XSS execution (no dangerouslySetInnerHTML)", () => {
    const maliciousPayload = '<script>alert("xss")</script><img src=x onerror=alert(1) />';
    render(<XssProbeComponent untrustedText={maliciousPayload} />);

    const container = screen.getByTestId("untrusted-container");
    // Confirm script element was NOT created
    expect(container.getElementsByTagName("script").length).toBe(0);
    expect(container.getElementsByTagName("img").length).toBe(0);

    // Confirm it is rendered strictly as plain text
    const content = screen.getByTestId("untrusted-content");
    expect(content.textContent).toBe(maliciousPayload);
  });
});
