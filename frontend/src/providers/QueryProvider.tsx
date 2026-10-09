import React, { useEffect, useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useApiConfig } from "../hooks/useApiConfig";

let nextScopeId = 0;

const createQueryClient = () => new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
      refetchIntervalInBackground: false,
      staleTime: 5000,
    },
    mutations: {
      retry: 0, // Never auto-retry mutations (acknowledge / resolve)
    },
  },
});

export const QueryProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { client } = useApiConfig();
  const scope = useMemo(() => ({
    connection: client,
    id: ++nextScopeId,
    queryClient: createQueryClient(),
  }), [client]);

  useEffect(() => () => {
    void scope.queryClient.cancelQueries();
    scope.queryClient.clear();
  }, [scope]);

  // Remount observers and mutation state when credentials or the server change.
  // A numeric key keeps credentials out of React keys and cached query keys.
  return <QueryClientProvider key={scope.id} client={scope.queryClient}>{children}</QueryClientProvider>;
};
