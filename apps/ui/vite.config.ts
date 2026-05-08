import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig, type Plugin, type ViteDevServer } from 'vite'

function requestLogger(): Plugin {
  return {
    configureServer(server: ViteDevServer) {
      server.middlewares.use((req, res, next) => {
        console.log(`${req.method} ${req.url}`)
        next()
      })
    },
    name: 'request-logger',
  }
}

export default defineConfig({
  build: {
    outDir: 'dist',
    rollupOptions: {
      output: {
        manualChunks: {
          markdown: ['react-markdown', 'remark-gfm'],
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          tanstack: ['@tanstack/react-query', '@tanstack/react-virtual'],
          three: [
            'reagraph',
            '@react-three/fiber',
            '@react-three/drei',
            '@react-spring/three',
            'three',
          ],
        },
      },
    },
  },
  esbuild: {
    drop: ['console'],
  },
  plugins: [react(), requestLogger()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    dedupe: ['react', 'react-dom', '@react-three/fiber', 'three'],
  },
  root: path.resolve(__dirname),
  server: {
    allowedHosts: true,
    cors: true,
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        target: process.env.VITE_API_URL || 'http://localhost:8000',
      },
      '/uploads': {
        changeOrigin: true,
        target: process.env.VITE_API_URL || 'http://localhost:8000',
      },
    },
  },
})
