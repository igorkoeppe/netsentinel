import React, { useMemo, useState } from "react";
import { ApiClient } from "../api/client";
import { ApiConfigContext } from "./ApiConfigContext";

export { type ApiConfigContextType } from "./ApiConfigContext";

const SESSION_API_KEY = "netsentinel_session_api_key";
const STORAGE_POLL_INTERVAL = "netsentinel_poll_interval";

export const ApiConfigProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [baseUrl, setBaseUrl] = useState<string>(() => {
    // Optional env override (public fallback, never contains secrets)
    const envUrl = (import.meta as unknown as { env?: { VITE_NETSENTINEL_API_BASE_URL?: string } }).env
      ?.VITE_NETSENTINEL_API_BASE_URL;
    return envUrl && envUrl.trim() ? envUrl.trim() : "/api/v1";
  });

  const [rememberKeyInSession, setRememberKeyInSession] = useState<boolean>(() => {
    if (typeof window !== "undefined" && window.sessionStorage) {
      return Boolean(sessionStorage.getItem(SESSION_API_KEY));
    }
    return false;
  });

  const [apiKey, setApiKeyState] = useState<string | null>(() => {
    if (typeof window !== "undefined" && window.sessionStorage) {
      const stored = sessionStorage.getItem(SESSION_API_KEY);
      if (stored) {
        return stored;
      }
    }
    return null;
  });

  const [pollInterval, setPollIntervalState] = useState<number>(() => {
    if (typeof window !== "undefined" && window.localStorage) {
      const saved = localStorage.getItem(STORAGE_POLL_INTERVAL);
      if (saved !== null) {
        const parsed = parseInt(saved, 10);
        if (!isNaN(parsed) && parsed >= 0) {
          return parsed;
        }
      }
    }
    return 10000; // 10s default
  });

  const setApiKey = (key: string | null, remember?: boolean) => {
    const trimmed = key ? key.trim() : null;
    setApiKeyState(trimmed);

    const shouldRemember = remember !== undefined ? remember : rememberKeyInSession;
    if (shouldRemember && trimmed) {
      sessionStorage.setItem(SESSION_API_KEY, trimmed);
    } else {
      sessionStorage.removeItem(SESSION_API_KEY);
    }
  };

  const clearApiKey = () => {
    setApiKeyState(null);
    if (typeof window !== "undefined" && window.sessionStorage) {
      sessionStorage.removeItem(SESSION_API_KEY);
    }
  };

  const setPollInterval = (interval: number) => {
    setPollIntervalState(interval);
    if (typeof window !== "undefined" && window.localStorage) {
      localStorage.setItem(STORAGE_POLL_INTERVAL, String(interval));
    }
  };

  const client = useMemo(() => {
    return new ApiClient(
      () => baseUrl,
      () => apiKey
    );
  }, [baseUrl, apiKey]);

  return (
    <ApiConfigContext.Provider
      value={{
        baseUrl,
        setBaseUrl,
        apiKey,
        setApiKey,
        clearApiKey,
        rememberKeyInSession,
        setRememberKeyInSession,
        pollInterval,
        setPollInterval,
        client,
      }}
    >
      {children}
    </ApiConfigContext.Provider>
  );
};
