import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { initTelegram } from "./lib/telegram.js";
import { AppProvider } from "./store/AppContext.jsx";
import App from "./App.jsx";

initTelegram();

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </StrictMode>
);
