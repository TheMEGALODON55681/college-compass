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
      "/report": BACKEND,
      "/meta": BACKEND,
      "/similar": BACKEND,
      "/health": BACKEND,
    },
  },
});
