import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

function requestLogger() {
  return {
    name: 'request-logger',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        console.log(`${req.method} ${req.url}`)
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), requestLogger()],
  root: path.resolve(__dirname),
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    dedupe: ['react', 'react-dom', '@react-three/fiber', 'three'],
  },
  build: {
    outDir: 'dist',
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    cors: true,
    allowedHosts: true,
  },
})
