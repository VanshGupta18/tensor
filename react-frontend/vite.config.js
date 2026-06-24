import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Output directly into CAP's app/ folder so cds build bundles it into gen/srv
    outDir: '../cap-backend/app',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // Proxy all /api requests to the local CAP server on port 4004
      '/api': {
        target: 'http://localhost:4004',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // Dedicated multipart upload route — raw binary, no base64 inflation
      '/upload': {
        target:       'http://localhost:4004',
        changeOrigin: true,
        timeout:      600000,    // 10 min — AI processing can be slow
        proxyTimeout: 600000,
      },
    },
  },
})
