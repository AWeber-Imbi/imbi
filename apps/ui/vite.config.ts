import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { execSync } from 'child_process'
import path from 'path'
import { defineConfig, type Plugin, type ViteDevServer } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

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
  plugins: [
    tailwindcss(),
    react(),
    requestLogger(),
    versionManifest(),
    VitePWA({
      devOptions: {
        // Keep the SW out of `vite dev` — matches useVersionCheck, which is
        // also a no-op in DEV, and avoids stale-cache confusion during HMR.
        enabled: false,
      },
      // We register the service worker by hand (src/lib/pwa.ts) so the
      // "update available" prompt can reuse the existing sonner toast and
      // drive skipWaiting. 'prompt' keeps a new SW in `waiting` until the
      // user accepts, rather than swapping chunks out from under an open tab.
      injectRegister: false,
      manifest: {
        background_color: '#ffffff',
        description: 'Service catalog and project operations platform',
        display: 'standalone',
        icons: [
          {
            purpose: 'any',
            sizes: '192x192',
            src: '/icons/pwa-192x192.png',
            type: 'image/png',
          },
          {
            purpose: 'any',
            sizes: '512x512',
            src: '/icons/pwa-512x512.png',
            type: 'image/png',
          },
          {
            purpose: 'maskable',
            sizes: '512x512',
            src: '/icons/maskable-512x512.png',
            type: 'image/png',
          },
        ],
        id: '/',
        name: 'Imbi',
        scope: '/',
        short_name: 'Imbi',
        start_url: '/',
        theme_color: '#ffffff',
      },
      registerType: 'prompt',
      // The oversized icon-font chunks above are intentionally not precached;
      // warn instead of failing the build on the expected size notice.
      showMaximumFileSizeToCacheInBytesWarning: true,
      workbox: {
        cleanupOutdatedCaches: true,
        // Precache only the app shell — the entry chunk, its shared vendor
        // chunks, and the stylesheet. These are hashed and change on every
        // deploy, so the generated SW also changes, which is what drives the
        // update prompt. The app code-splits into ~1900 per-icon and per-route
        // chunks; precaching all of them would mean a ~10 MB install, so they
        // are left to the runtime rule below and cached only when used.
        //
        // index.html is deliberately NOT precached: Caddy templates
        // `{{env …}}` into it at request time and serves it no-cache, so it
        // must always come from the network — precaching the raw build
        // artifact would ship the un-substituted `{{env "VITE_API_URL"}}`
        // placeholder to clients.
        globPatterns: [
          'assets/index-*.css',
          'assets/index-*.js',
          'assets/react-vendor-*.js',
          'assets/tanstack-*.js',
        ],
        // The multi-MB icon-font chunks (phosphor, simple-icons, tabler)
        // aren't in the precache set above, but keep the cap so an accidental
        // large precache entry can't slip in unnoticed.
        maximumFileSizeToCacheInBytes: 2 * 1024 * 1024,
        // No offline shell: navigations always hit the network (and Caddy's
        // template). The app gates every route on a live API anyway.
        navigateFallback: null,
        runtimeCaching: [
          {
            handler: 'CacheFirst',
            options: {
              cacheableResponse: { statuses: [0, 200] },
              cacheName: 'imbi-assets',
              expiration: {
                maxAgeSeconds: 60 * 60 * 24 * 30,
                maxEntries: 200,
              },
            },
            // Hashed asset filenames are immutable, so CacheFirst is safe:
            // a new build emits new names and never reuses a cached one.
            // This warms repeat loads for chunks too large to precache.
            urlPattern: /\/assets\/.*\.(?:js|css|woff2?)$/,
          },
        ],
      },
    }),
  ],
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
