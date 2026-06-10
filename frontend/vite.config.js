import { defineConfig } from "vite";

const backendTarget = "http://127.0.0.1:8000";

export default defineConfig({
  server: {
    proxy: {
      "/schema": backendTarget,
      "/view": backendTarget,
      "/health": backendTarget,
    },
  },
});

