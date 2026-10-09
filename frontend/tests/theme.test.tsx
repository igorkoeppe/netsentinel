import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "../src/providers/ThemeProvider";
import { useTheme } from "../src/hooks/useTheme";

const TestThemeComponent: React.FC = () => {
  const { theme, effectiveTheme, setTheme } = useTheme();

  return (
    <div>
      <span data-testid="current-theme">{theme}</span>
      <span data-testid="effective-theme">{effectiveTheme}</span>
      <button onClick={() => setTheme("light")} data-testid="set-light-btn">
        Light
      </button>
      <button onClick={() => setTheme("dark")} data-testid="set-dark-btn">
        Dark
      </button>
      <button onClick={() => setTheme("system")} data-testid="set-system-btn">
        System
      </button>
    </div>
  );
};

describe("Theme System", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("defaults to system theme and respects prefers-color-scheme", () => {
    render(
      <ThemeProvider>
        <TestThemeComponent />
      </ThemeProvider>
    );

    expect(screen.getByTestId("current-theme")).toHaveTextContent("system");
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
  });

  it("switches theme to dark and light and persists to localStorage", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <TestThemeComponent />
      </ThemeProvider>
    );

    // Switch to dark
    await user.click(screen.getByTestId("set-dark-btn"));
    expect(screen.getByTestId("current-theme")).toHaveTextContent("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("netsentinel_theme")).toBe("dark");

    // Switch to light
    await user.click(screen.getByTestId("set-light-btn"));
    expect(screen.getByTestId("current-theme")).toHaveTextContent("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("netsentinel_theme")).toBe("light");

    // Switch back to system
    await user.click(screen.getByTestId("set-system-btn"));
    expect(screen.getByTestId("current-theme")).toHaveTextContent("system");
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
    expect(localStorage.getItem("netsentinel_theme")).toBe("system");
  });

  it("restores previously saved theme from localStorage on load", () => {
    localStorage.setItem("netsentinel_theme", "dark");

    render(
      <ThemeProvider>
        <TestThemeComponent />
      </ThemeProvider>
    );

    expect(screen.getByTestId("current-theme")).toHaveTextContent("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});
