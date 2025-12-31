import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // Use IMBI_TOKEN from system environment, or VITE_API_TOKEN from .env
  const apiToken = process.env.IMBI_TOKEN || env.VITE_API_TOKEN

  console.log('[Vite] Proxy target:', env.VITE_PROXY_TARGET || 'https://imbi.aweber.io')
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
          target: env.VITE_PROXY_TARGET || 'https://imbi.aweber.io',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
          configure: (proxy, _options) => {
            proxy.on('proxyReq', (proxyReq, req, _res) => {
              // Add API token if available
              if (apiToken) {
                proxyReq.setHeader('Private-Token', apiToken)
              }
              // Log requests in development
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
