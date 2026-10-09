import { useContext } from "react";
import { ApiConfigContext, type ApiConfigContextType } from "../providers/ApiConfigContext";

export function useApiConfig(): ApiConfigContextType {
  const context = useContext(ApiConfigContext);
  if (!context) {
    throw new Error("useApiConfig must be used within an ApiConfigProvider");
  }
  return context;
}
