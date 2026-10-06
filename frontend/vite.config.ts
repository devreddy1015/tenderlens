import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Long-lived chunks: the framework and the state outlines change far less often than
        // the app, so a deploy only re-downloads the app code.
        manualChunks(id) {
          if (id.includes("india-states.json")) return "india-geo";
          if (/node_modules\/(react|react-dom|react-router|scheduler|@tanstack)\//.test(id)) return "vendor";
        },
      },
    },
  },
  test: {
    environment: "jsdom",
  },
});
