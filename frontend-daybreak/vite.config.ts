import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// api/main.py mounts every endpoint at the app root, no /api prefix, so the
// dev proxy forwards those exact root paths to the backend instead of a
// blanket prefix. Avoids CORS friction between the Vite dev server and
// uvicorn on :8000. See .planning/Architecture.md.
const BACKEND = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/recommend": BACKEND,
      "/chat": BACKEND,
      // "/report" is also the frontend's own route (Architecture.md), so only
      // POST (the real PDF download call) proxies to the backend. A GET - a
      // full page load or refresh on /report - bypasses so Vite's own SPA
      // fallback serves the app instead of hitting the POST-only backend
      // endpoint and 405ing.
      "/report": {
        target: BACKEND,
        bypass: (req) => {
          if (req.method !== "POST") return req.url;
        },
      },
      "/meta": BACKEND,
      "/similar": BACKEND,
      "/cutoffs": BACKEND,
      "/health": BACKEND,
    },
  },
});
