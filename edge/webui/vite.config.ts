import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react()],
    base: env.VITE_PUBLIC_PATH || "/",
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    build: {
      outDir: "dist",
      sourcemap: true,
    },
    server: {
      port: Number(env.VITE_DEV_PORT || 5173),
      proxy: env.VITE_API_PROXY
        ? {
            [env.VITE_API_PROXY]: {
              target: env.VITE_API_TARGET || "http://127.0.0.1:8000",
              changeOrigin: true,
              rewrite: (path) => path.replace(env.VITE_API_PROXY as string, ""),
            },
          }
        : undefined,
    },
  };
});
