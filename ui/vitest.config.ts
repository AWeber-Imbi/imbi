import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: '@/test', replacement: path.resolve(__dirname, './test') },
      { find: '@', replacement: path.resolve(__dirname, './src') },
    ],
  },
  test: {
    coverage: {
      exclude: [
        'node_modules/',
        'test/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/mockData',
        'src/main.tsx',
      ],
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
    },
    css: true,
    environment: 'jsdom',
    exclude: ['node_modules', 'dist', '.idea', '.git', '.cache'],
    globals: true,
    include: [
      'src/**/*.{test,spec}.{ts,tsx}',
      'tools/**/*.{test,spec}.{ts,js}',
    ],
    setupFiles: './test/setup.ts',
  },
})
