import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the panel talks to the Django backend on :8000 through this proxy,
// so the browser sees one origin (same as production behind nginx).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.API_TARGET || "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { chunkSizeWarningLimit: 2000 },
});
