const defaultTheme = require('tailwindcss/defaultTheme')

module.exports = {
  purge: [
    '../imbi/templates/*.html'
  ],
  darkMode: false,
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter var', ...defaultTheme.fontFamily.sans],
      }
    },
  },
  variants: {
    extend: {},
  },
  plugins: [],
}
