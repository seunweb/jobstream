import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  server: {
    port: 3000,
    proxy: {
      // Proxy all API calls to FastAPI backend in development
      "/auth": "http://localhost:8000",
      "/jobs": "http://localhost:8000",
      "/companies": "http://localhost:8000",
      "/organizations": "http://localhost:8000",
      "/applications": "http://localhost:8000",
      "/scrape": "http://localhost:8000",
      "/billing": "http://localhost:8000",
      "/analytics": "http://localhost:8000",
      "/ai": "http://localhost:8000",
      "/rbac": "http://localhost:8000",
      "/admin": "http://localhost:8000",
      "/workspace": "http://localhost:8000",
      "/persons": "http://localhost:8000",
      "/departments": "http://localhost:8000",
      "/job-alerts": "http://localhost:8000",
      "/track": "http://localhost:8000",
      "/sitemap": "http://localhost:8000",
    },
    watch: {
      usePolling: true,
      interval: 500,
    },
  },
  optimizeDeps: {
    entries: ["./src/main.jsx"],
  },
});
