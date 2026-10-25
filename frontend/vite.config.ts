import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// Dev:   `npm run dev`  -> http://localhost:5173 (hot reload). Requests to /api are forwarded to the Python backend,
//        so the browser sees ONE origin and the login cookie just works.
// Build: `npm run build` -> frontend/dist, which the backend serves in production (one URL for the whole app).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: { '/api': { target: process.env.BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { outDir: 'dist', sourcemap: false },
})
