import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: Vite on 5173 proxies /api/* to FastAPI on 8000.
// Prod: build to dist/, served alongside the API on the same origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
