import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Set VITE_API_TARGET to proxy to a different backend:
//   VITE_API_TARGET=https://www.paperignition.com npm run dev  (production)
//   npm run dev                                                (local :8000)
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, secure: false },
      '/find_similar': { target: apiTarget, changeOrigin: true, secure: false },
      '/paper_content': { target: apiTarget, changeOrigin: true, secure: false },
      '/get_metadata': { target: apiTarget, changeOrigin: true, secure: false },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, secure: false },
      '/find_similar': { target: apiTarget, changeOrigin: true, secure: false },
      '/paper_content': { target: apiTarget, changeOrigin: true, secure: false },
      '/get_metadata': { target: apiTarget, changeOrigin: true, secure: false },
    },
  },
  build: {
    outDir: 'dist',
  },
})
