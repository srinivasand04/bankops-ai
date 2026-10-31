import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Dev proxy so the browser talks to one origin; backend runs on :8000
    proxy: { "/api": "http://localhost:8000" },
  },
});
