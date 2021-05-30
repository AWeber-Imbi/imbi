const defaultTheme = require('tailwindcss/defaultTheme')

module.exports = {
  purge: ['./**/*.{js,jsx,ts,tsx}'],
  darkMode: 'media',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter var', ...defaultTheme.fontFamily.sans]
      }
    }
  },
  variants: {
    extend: {
      backgroundColor: ['disabled']
    }
  },
  plugins: [require('@tailwindcss/forms')]
}
