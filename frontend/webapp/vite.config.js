import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app is served from its own static host at the root, so base defaults to
// "/". Override with VITE_BASE only if hosting under a sub-path.
export default defineConfig({
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
});
