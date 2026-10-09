import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ThemeProvider } from "./providers/ThemeProvider";
import { ApiConfigProvider } from "./providers/ApiConfigProvider";
import { QueryProvider } from "./providers/QueryProvider";
import { App } from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <ApiConfigProvider>
        <QueryProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryProvider>
      </ApiConfigProvider>
    </ThemeProvider>
  </React.StrictMode>
);
