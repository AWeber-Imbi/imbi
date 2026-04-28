import { type Config } from 'prettier'

const config: Config = {
  plugins: ['prettier-plugin-packagejson', 'prettier-plugin-tailwindcss'],
  semi: false,
  singleQuote: true,
  tabWidth: 2,
  trailingComma: 'all',
}

export default config
