import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/login': 'http://127.0.0.1:8765',
      '/logout': 'http://127.0.0.1:8765',
      '/auth': 'http://127.0.0.1:8765',
    },
  },
})
