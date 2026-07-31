import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Im Entwicklungsbetrieb läuft das Backend getrennt auf Port 8099.
const backend = process.env.FDB_DEV_BACKEND ?? 'http://127.0.0.1:8099'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
        // Server-Sent Events dürfen nicht gepuffert werden
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
            }
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 900,
  },
})
