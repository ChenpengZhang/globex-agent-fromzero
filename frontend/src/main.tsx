import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./styles.css";


const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("缺少 React 根节点 #root");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
