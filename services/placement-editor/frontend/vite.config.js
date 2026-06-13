import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build into ../static so the FastAPI process serves the bundle as-is.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../static",
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    proxy: {
      "/api": "http://localhost:8080",
    },
  },
});
