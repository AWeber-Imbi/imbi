import { defineConfig, type ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

type ProxyServer = Parameters<NonNullable<ProxyOptions['configure']>>[0]

/**
 * Attach standard request-logging and error-logging handlers to a proxy.
 * Pass `extra` for route-specific behaviour (auth headers, SSE headers, etc.).
 */
function configureProxy(
  extra?: (proxy: ProxyServer) => void
): ProxyOptions['configure'] {
  return (proxy) => {
    proxy.on('proxyReq', (proxyReq, req) => {
      console.log(`[Proxy] ${req.method} ${req.url} -> ${proxyReq.path}`)
    })
    proxy.on('error', (err) => {
      console.log('[Proxy] Error:', err.message)
    })
    extra?.(proxy)
  }
}

// https://vitejs.dev/config/
export default defineConfig(({ mode: _mode }) => {
  const apiToken = process.env.IMBI_TOKEN || process.env.VITE_API_TOKEN
  const apiTarget = process.env.IMBI_API_URL || 'http://127.0.0.1:8000'
  const assistantTarget = process.env.IMBI_ASSISTANT_URL || 'http://127.0.0.1:8002'
  const gatewayTarget = process.env.IMBI_GATEWAY_URL || 'http://127.0.0.1:8003'

  console.log('[Vite] API token configured:', !!apiToken)

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
      dedupe: ['react', 'react-dom', '@react-three/fiber', 'three'],
    },
    server: {
      port: 3000,
      allowedHosts: true,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (url) => url.replace(/^\/api/, ''),
          configure: configureProxy((proxy) => {
            if (apiToken) {
              proxy.on('proxyReq', (proxyReq) => {
                proxyReq.setHeader('Private-Token', apiToken)
              })
            }
          }),
        },
        '/uploads': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/assistant': {
          target: assistantTarget,
          changeOrigin: true,
          rewrite: (url) => url.replace(/^\/assistant/, ''),
          // Disable timeouts for SSE streaming connections
          proxyTimeout: 0,
          timeout: 0,
          configure: configureProxy((proxy) => {
            proxy.on('proxyReq', (proxyReq, req) => {
              if (req.headers.accept?.includes('text/event-stream')) {
                proxyReq.setHeader('Accept', 'text/event-stream')
              }
            })
            proxy.on('proxyRes', (proxyRes) => {
              proxyRes.headers['cache-control'] ??= 'no-cache'
              proxyRes.headers['connection'] ??= 'keep-alive'
            })
          }),
        },
        '/gateway': {
          target: gatewayTarget,
          changeOrigin: true,
          rewrite: (url) => url.replace(/^\/gateway/, ''),
          configure: configureProxy(),
        },
      },
    },
  }
})
