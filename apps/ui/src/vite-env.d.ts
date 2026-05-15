/// <reference types="vite/client" />

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface ImportMetaEnv {
  readonly VITE_API_TOKEN?: string
  readonly VITE_API_URL: string
  readonly VITE_OAUTH_CLIENT_ID?: string
  readonly VITE_OAUTH_REDIRECT_URI?: string
  readonly VITE_SENTRY_DSN?: string
}

interface Window {
  __IMBI_API_URL__?: string
  __IMBI_SENTRY_DSN__?: string
}
