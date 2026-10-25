import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API goes to the gateway on :8000; in Compose nginx does the same (nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", rewrite: (path) => path.replace(/^\/api/, "") },
    },
  },
});
