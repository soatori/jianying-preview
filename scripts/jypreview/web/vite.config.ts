import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** The Python service owns the origin; the bundle is served from under its web root. */
const PREVIEW_PORT = process.env.JY_PREVIEW_PORT ?? "8765";
const python = { target: `http://127.0.0.1:${PREVIEW_PORT}`, changeOrigin: false };

export default defineConfig({
  base: "/web/dist/",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: { input: "editor.html" },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ["/api", "/media", "/font", "/image", "/thumb", "/effect", "/effectstyle"].map((path) => [path, python]),
    ),
  },
  // Component tests opt into jsdom with a `@vitest-environment` docblock.
  test: { environment: "node" },
});
