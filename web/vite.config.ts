/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The Python server serves the build (dist/) at "/". In development, Vite serves the page and
// proxies /api to the backend started with --dev-origin http://localhost:5173 (see API.md).
const backend = process.env.SETDL_BACKEND ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Fonts stay files next to the CSS (no data: URIs), and WKWebView on recent macOS runs it all
    assetsInlineLimit: 0,
    target: "safari16",
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: backend, changeOrigin: true } },
  },
  test: {
    environment: "happy-dom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
  },
});
