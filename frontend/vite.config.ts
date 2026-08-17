import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// The dashboard is served at /kindling/ in production, so all built assets
// (JS, CSS, favicon) must resolve under that prefix too. Without `base`,
// Vite emits /assets/... references which only resolve coincidentally when
// the SPA catch-all serves them. With `base: '/kindling/'` the emitted
// index.html references /kindling/assets/index-*.js etc.
export default defineConfig({
  base: "/kindling/",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
