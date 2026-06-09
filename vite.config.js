import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    watch: {
      // Use polling for Windows file system compatibility
      usePolling: true,
      interval: 500,
    },
  },
  optimizeDeps: {
    entries: ["./src/main.jsx"],
  },
});
