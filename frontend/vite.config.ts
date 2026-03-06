import { defineConfig } from 'vite'
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
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  server: {
    proxy: {
      "/v1": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
      "/ready": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
})
