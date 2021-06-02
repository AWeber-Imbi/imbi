const defaultTheme = require('tailwindcss/defaultTheme')

module.exports = {
  purge: ['./**/*.{js,jsx,ts,tsx}'],
  darkMode: 'media',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter var', ...defaultTheme.fontFamily.sans]
      },
      height: {
        'screen-1/2': '50vh',
        'screen-1/3': 'calc(100vh / 3)',
        'screen-1/4': 'calc(100vh / 4)',
        'screen1-/5': 'calc(100vh / 5)'
      }
    }
  },
  variants: {
    extend: {
      backgroundColor: ['disabled']
    },
    display: ['responsive', 'hover', 'focus']
  },
  plugins: [require('@tailwindcss/forms')]
}
