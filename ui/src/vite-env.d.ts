/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

declare const __APP_VERSION__: string

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface ImportMetaEnv {
  readonly VITE_API_TOKEN?: string
  readonly VITE_API_URL: string
  readonly VITE_DRIFT_STALE_AFTER?: string
  readonly VITE_OAUTH_CLIENT_ID?: string
  readonly VITE_OAUTH_REDIRECT_URI?: string
  readonly VITE_POSTHOG_ERROR_TRACKING?: string
  readonly VITE_POSTHOG_HOST?: string
  readonly VITE_POSTHOG_KEY?: string
  readonly VITE_POSTHOG_PERSON_PROFILES?: string
  readonly VITE_POSTHOG_REPLAY_SAMPLE_RATE?: string
  readonly VITE_POSTHOG_SESSION_REPLAY?: string
  readonly VITE_POSTHOG_WEB_ANALYTICS?: string
  readonly VITE_SENTRY_DSN?: string
}

interface Window {
  __IMBI_API_URL__?: string
  __IMBI_DRIFT_STALE_AFTER__?: string
  __IMBI_POSTHOG_ERROR_TRACKING__?: string
  __IMBI_POSTHOG_HOST__?: string
  __IMBI_POSTHOG_KEY__?: string
  __IMBI_POSTHOG_PERSON_PROFILES__?: string
  __IMBI_POSTHOG_REPLAY_SAMPLE_RATE__?: string
  __IMBI_POSTHOG_SESSION_REPLAY__?: string
  __IMBI_POSTHOG_WEB_ANALYTICS__?: string
  __IMBI_SENTRY_DSN__?: string
}
