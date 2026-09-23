// Library build of ui/src/components/ui for design-sync. Run from ui/ via
// build.sh. Tailwind scans ui/ (the vite root), so the emitted CSS holds
// every utility the app uses.
import { createRequire } from 'module'
import path from 'path'
import { pathToFileURL } from 'url'

const UI = path.resolve(__dirname, '../../ui')
const OUT = path.resolve(__dirname, '../.cache/lib-dist')

// This file lives outside ui/, so resolve the plugins from ui/node_modules.
const uiRequire = createRequire(path.join(UI, 'package.json'))
const load = async (name: string) =>
  (await import(pathToFileURL(uiRequire.resolve(name)).href)).default

// ImbiProvider.tsx and the generated entry sit outside ui/, so their bare
// imports would miss ui/node_modules. Resolve them as if imported from ui/src.
const resolveFromUi = {
  enforce: 'pre' as const,
  name: 'resolve-from-ui',
  async resolveId(this: any, id: string, importer?: string) {
    const local = /^(\.|\/|@\/|\0)/.test(id)
    if (!importer || importer.startsWith(UI) || local) return null
    return this.resolve(id, path.join(UI, 'src/main.tsx'), { skipSelf: true })
  },
}

// The on-demand icon sets (thousands of SVGs and icon components) make the
// bundle exceed the 12 MB upload limit. Stub all sets except Lucide, which
// the primitives import directly. Stubbed sets load with no icons.
const STUBBED_SETS: Record<string, [string, string]> = {
  aws: ['AWS', '{service-name}'],
  devicon: ['Devicon', 'devicon-{tech}-{variant}'],
  phosphor: ['Phosphor', 'phosphor-{name}'],
  'simple-icons': ['Simple Icons', 'si-{name}'],
  tabler: ['Tabler', 'tabler-{name}'],
}
const stubIconSets = {
  enforce: 'pre' as const,
  load(id: string) {
    const m = /^\0icon-set-stub:(.+)$/.exec(id)
    if (!m) return null
    const [label, valueFormat] = STUBBED_SETS[m[1]]
    const meta = JSON.stringify({
      description: 'Not included in the design-sync bundle',
      icons: [],
      id: m[1],
      label,
      valueFormat,
    })
    return `export const iconSet = { ...${meta}, resolve: () => null, resolveUrl: () => null }`
  },
  name: 'stub-icon-sets',
  resolveId(id: string) {
    const m = /\/lib\/icon-sets\/([a-z-]+)(\.ts)?$/.exec(id)
    return m && m[1] in STUBBED_SETS ? `\0icon-set-stub:${m[1]}` : null
  },
}

export default async () => {
  const tailwindcss = await load('@tailwindcss/vite')
  const react = await load('@vitejs/plugin-react')
  return {
    build: {
      cssCodeSplit: false,
      emptyOutDir: true,
      lib: {
        entry: path.resolve(__dirname, '../.cache/lib-src/index.tsx'),
        fileName: () => 'index.js',
        formats: ['es'],
      },
      outDir: OUT,
      rollupOptions: {
        external: [/^react($|\/)/, /^react-dom($|\/)/],
        output: { assetFileNames: 'style.css', inlineDynamicImports: true },
      },
    },
    define: {
      __APP_VERSION__: JSON.stringify('design-sync'),
      'process.env.NODE_ENV': JSON.stringify('production'),
    },
    publicDir: false,
    plugins: [stubIconSets, resolveFromUi, react(), tailwindcss()],
    resolve: { alias: { '@': path.resolve(UI, 'src') } },
    root: UI,
  }
}
