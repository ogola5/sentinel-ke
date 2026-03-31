import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const manualChunks = (id: string) => {
  if (!id.includes("node_modules")) return undefined

  if (
    id.includes("/node_modules/recharts/") ||
    id.includes("/node_modules/victory-vendor/") ||
    id.includes("/node_modules/d3-") ||
    id.includes("/node_modules/react-smooth/")
  ) {
    return "charts-vendor"
  }

  if (id.includes("/node_modules/lucide-react/")) {
    return "icons-vendor"
  }

  if (
    id.includes("/node_modules/react/") ||
    id.includes("/node_modules/react-dom/") ||
    id.includes("/node_modules/scheduler/")
  ) {
    return "react-vendor"
  }

  return "vendor"
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  const proxyTarget = env.VITE_API_PROXY_TARGET || "http://localhost:8000"
  const allowedHosts = (env.VITE_ALLOWED_HOSTS || ".ts.net,localhost,127.0.0.1")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)

  return {
    plugins: [react()],
    build: {
      rollupOptions: {
        output: {
          manualChunks,
        },
      },
    },
    server: {
      allowedHosts,
      proxy: {
        "/v1": {
          target: proxyTarget,
          changeOrigin: true,
        },
        "/health": {
          target: proxyTarget,
          changeOrigin: true,
        },
        "/ready": {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
