import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // Use IMBI_TOKEN from system environment, or VITE_API_TOKEN from .env
  const apiToken = process.env.IMBI_TOKEN || env.VITE_API_TOKEN

  console.log('[Vite] API token configured:', !!apiToken)

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 3000,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
          configure: (proxy, _options) => {
            proxy.on('proxyReq', (proxyReq, req, _res) => {
              if (apiToken) {
                proxyReq.setHeader('Private-Token', apiToken)
              }
              console.log(`[Proxy] ${req.method} ${req.url} -> ${proxyReq.path}`)
            })
            proxy.on('error', (err, _req, _res) => {
              console.log('[Proxy] Error:', err.message)
            })
          },
        },
        '/assistant': {
          target: 'http://127.0.0.1:8002',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/assistant/, ''),
          configure: (proxy, _options) => {
            proxy.on('proxyReq', (proxyReq, req, _res) => {
              console.log(`[Proxy] ${req.method} ${req.url} -> ${proxyReq.path}`)
            })
            proxy.on('error', (err, _req, _res) => {
              console.log('[Proxy] Error:', err.message)
            })
          },
        },
        '/gateway': {
          target: 'http://127.0.0.1:8003',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/gateway/, ''),
          configure: (proxy, _options) => {
            proxy.on('proxyReq', (proxyReq, req, _res) => {
              console.log(`[Proxy] ${req.method} ${req.url} -> ${proxyReq.path}`)
            })
            proxy.on('error', (err, _req, _res) => {
              console.log('[Proxy] Error:', err.message)
            })
          },
        },
      },
    },
  }
})
