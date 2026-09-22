import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // Forwards to the django dev server so the browser sees a same-origin
      // request in development, avoiding the need for CORS headers on the
      // Django side.
      '/api': 'http://localhost:8000',
    },
  },
})
