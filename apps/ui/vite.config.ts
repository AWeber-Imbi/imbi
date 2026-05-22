import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { execSync } from 'child_process'
import path from 'path'
import { defineConfig, type Plugin, type ViteDevServer } from 'vite'

function resolveBuildId(): string {
  const fromEnv = process.env.VITE_GIT_REF?.trim()
  if (fromEnv && fromEnv !== 'latest') return fromEnv
  try {
    return execSync('git describe --tags --always --dirty', {
      cwd: __dirname,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim()
  } catch {
    return Date.now().toString()
  }
}

const BUILD_ID = resolveBuildId()

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

function versionManifest(): Plugin {
  return {
    apply: 'build',
    generateBundle() {
      this.emitFile({
        fileName: 'version.json',
        source: JSON.stringify({ version: BUILD_ID }),
        type: 'asset',
      })
    },
    name: 'version-manifest',
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
    sourcemap: true,
  },
  define: {
    __APP_VERSION__: JSON.stringify(BUILD_ID),
  },
  esbuild: {
    // Preserve console.error / console.warn so auth-failure diagnostics
    // (see useAuth.ts) survive in prod; strip the noisy levels only via
    // esbuild's `pure` annotation. (The pre-commit hook already blocks
    // breakpoint statements in source, so a `drop` list is unnecessary.)
    pure: ['console.log', 'console.debug', 'console.info'],
  },
  plugins: [tailwindcss(), react(), requestLogger(), versionManifest()],
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
