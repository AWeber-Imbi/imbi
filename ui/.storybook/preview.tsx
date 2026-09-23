import { withThemeByClassName } from '@storybook/addon-themes'
import type { Preview } from '@storybook/react-vite'

import '../src/index.css'

const preview: Preview = {
  decorators: [
    // Mirrors ThemeContext, which toggles `.dark` on <html>.
    withThemeByClassName({
      defaultTheme: 'light',
      parentSelector: 'html',
      themes: { dark: 'dark', light: '' },
    }),
  ],
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    layout: 'centered',
  },
  tags: ['autodocs'],
}

export default preview
