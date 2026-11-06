import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));
const frontend = fileURLToPath(new URL("../../../", import.meta.url));
export default defineConfig({
  root,
  plugins: [
    {
      name: "isolated-transcript-preview",
      enforce: "pre",
      resolveId(source, importer) {
        if (source === "../../lib/api" && importer?.replaceAll("\\", "/").endsWith("/components/chat/AgentTranscript.tsx")) {
          return fileURLToPath(new URL("./api.ts", import.meta.url));
        }
      },
    },
    react(),
  ],
  css: { postcss: frontend },
  server: { host: "127.0.0.1", port: 3109, strictPort: true, fs: { allow: [frontend] } },
});
