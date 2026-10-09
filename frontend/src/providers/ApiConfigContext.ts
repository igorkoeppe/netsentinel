import { createContext } from "react";
import type { ApiClient } from "../api/client";

export interface ApiConfigContextType {
  baseUrl: string;
  setBaseUrl: (url: string) => void;
  apiKey: string | null;
  setApiKey: (key: string | null, rememberInSession?: boolean) => void;
  clearApiKey: () => void;
  rememberKeyInSession: boolean;
  setRememberKeyInSession: (remember: boolean) => void;
  pollInterval: number; // in milliseconds, 0 means Off
  setPollInterval: (interval: number) => void;
  client: ApiClient;
}

export const ApiConfigContext = createContext<ApiConfigContextType | undefined>(undefined);
