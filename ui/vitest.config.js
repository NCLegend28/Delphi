import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Vitest config — kept separate from vite.config.js so the dev/build pipeline
// is unchanged. jsdom env powers @testing-library/react.
export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.js"],
    css: false,
    include: ["src/**/*.{test,spec}.{js,jsx}"],
    // The samsungT7 drive (HFS-compatible) sprays AppleDouble ._* sidecar
    // files next to every real file. Skip them so they don't show up as
    // empty/broken test suites.
    exclude: ["**/node_modules/**", "**/._*"],
  },
});
