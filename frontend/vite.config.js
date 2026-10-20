import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: Number(process.env.PORT) || 3000,
    strictPort: false,
    proxy: {
      '/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})