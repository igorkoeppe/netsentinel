import React from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiConfigProvider } from "../src/providers/ApiConfigProvider";
import { ThemeProvider } from "../src/providers/ThemeProvider";
import { MemoryRouter } from "react-router-dom";

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function renderWithProviders(
  ui: React.ReactElement,
  {
    initialEntries = ["/"],
    queryClient = createTestQueryClient(),
  }: {
    initialEntries?: string[];
    queryClient?: QueryClient;
  } = {}
) {
  return render(
    <QueryClientProvider client={queryClient}>
      <ApiConfigProvider>
        <ThemeProvider>
          <MemoryRouter initialEntries={initialEntries}>
            {ui}
          </MemoryRouter>
        </ThemeProvider>
      </ApiConfigProvider>
    </QueryClientProvider>
  );
}
