import type { StorybookConfig } from '@storybook/react-vite'
import type { PluginOption } from 'vite'

// Plugins from vite.config.ts that only make sense for the real app shell:
// the PWA service worker / manifest, the build-time version.json emitter, and
// the dev-server request logger.
const APP_ONLY_PLUGINS = /^(vite-plugin-pwa|request-logger|version-manifest)/

function isAppOnly(plugin: PluginOption): boolean {
  return (
    !!plugin &&
    typeof plugin === 'object' &&
    'name' in plugin &&
    APP_ONLY_PLUGINS.test(plugin.name)
  )
}

const config: StorybookConfig = {
  addons: ['@storybook/addon-docs', '@storybook/addon-themes'],
  framework: '@storybook/react-vite',
  stories: ['../src/**/*.stories.@(ts|tsx)'],
  viteFinal(viteConfig) {
    return {
      ...viteConfig,
      // The app's manualChunks pins reagraph/three into a vendor chunk, which
      // Storybook's build doesn't need and which drags them into every story.
      build: { ...viteConfig.build, rollupOptions: {} },
      plugins: (viteConfig.plugins ?? [])
        .flat()
        .filter((plugin) => !isAppOnly(plugin)),
    }
  },
}

export default config
