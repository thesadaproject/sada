import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/source-sans-3";
import "@fontsource/eb-garamond/400.css";
import "@fontsource/amiri/400.css";
import "./styles.css";
import { App } from "./App";
import { lireBoot } from "./boot";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App boot={lireBoot()} />
  </StrictMode>,
);
