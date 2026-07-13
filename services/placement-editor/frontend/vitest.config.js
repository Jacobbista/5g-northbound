import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // The react plugin gives test files the same automatic JSX runtime as the
  // build, so component render tests (jsdom) work without importing React.
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: false,
  },
});
