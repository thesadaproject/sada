import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Pages publiques /m/<slug> : une entrée à part, sans le routeur, i18next ni hls de la console.
// Sur l'hôte public seul /api/v1/public/* atteint le back-office : les fichiers y vivent, noms hachés.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/api/v1/public/assets/p/",
  server: { port: 5174 },
  build: { outDir: "dist", emptyOutDir: true, assetsDir: ".", assetsInlineLimit: 0 },
});
