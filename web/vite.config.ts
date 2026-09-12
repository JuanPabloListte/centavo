import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Todo en 127.0.0.1: la interfaz no se expone a la red local, igual que la API.
// El proxy evita configurar CORS: el navegador sólo le habla a este servidor.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  preview: {
    host: '127.0.0.1',
  },
})
