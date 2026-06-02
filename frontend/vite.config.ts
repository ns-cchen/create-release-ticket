import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3005,
    proxy: {
      '/api': {
        target: 'http://localhost:5004',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    exclude: ['**/node_modules/**', '**/e2e/**'],
  },
})
