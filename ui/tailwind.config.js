const defaultTheme = require("tailwindcss/defaultTheme")

module.exports = {
  purge: [
    "./**/*.{js,jsx,ts,tsx}"
  ],
  darkMode: false,
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter var", ...defaultTheme.fontFamily.sans],
      }
    }
  },
  variants: {
    extend: {},
  },
  plugins: [
    require("@tailwindcss/forms")
  ],
}
