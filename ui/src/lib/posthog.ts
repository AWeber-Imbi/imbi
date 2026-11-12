import type { CaptureResult, PostHog } from 'posthog-js'

import { useAuthStore } from '@/stores/authStore'

const TOKEN_IN_URL = /[#?&]access_token=/

// The token subject is the user's email, which must not reach PostHog.
// The backend hashes it the same way (imbi.common.posthog.distinct_id).
export async function distinctId(subject: string): Promise<string> {
  const data = new TextEncoder().encode(subject.trim().toLowerCase())
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest), (b) =>
    b.toString(16).padStart(2, '0'),
  ).join('')
}

// The SDK loads only when a key is set, so a deployment without PostHog
// does not download it.
export async function initPostHog(): Promise<void> {
  const config = resolveConfig()
  if (!config.key) return

  // The OAuth callback arrives as /auth/callback#access_token=...; the
  // page removes it with replaceState. Start only after that, so no
  // event, replay snapshot, or person property can hold the token.
  while (TOKEN_IN_URL.test(window.location.href)) {
    await new Promise((resolve) => setTimeout(resolve, 100))
  }

  const { default: posthog } = await import('posthog-js')
  posthog.init(config.key, {
    api_host: config.host,
    // Web analytics: pageviews on SPA route changes, page leaves, vitals.
    autocapture: false,
    before_send: stripQueryStrings,
    capture_dead_clicks: false,
    capture_exceptions: config.errorTracking,
    capture_heatmaps: false,
    capture_pageleave: config.webAnalytics,
    capture_pageview: config.webAnalytics ? 'history_change' : false,
    capture_performance: {
      network_timing: false,
      web_vitals: config.webAnalytics,
    },
    disable_session_recording: !config.sessionReplay,
    disable_surveys: true,
    person_profiles: config.personProfiles,
    rageclick: false,
    // Always mask, no override: pages show API keys and secrets once.
    // Elements that show one carry `data-ph-no-capture`, which blocks
    // them from the recording completely.
    session_recording: {
      blockSelector: '[data-ph-no-capture]',
      maskAllInputs: true,
      // The initial navigation entry holds the page URL: drop its query.
      maskCapturedNetworkRequestFn: (request) => ({
        ...request,
        name: request.name.split(/[?#]/)[0],
      }),
      maskTextSelector: '*',
      recordBody: false,
      recordHeaders: false,
      sampleRate: config.replaySampleRate,
    },
  })

  if (config.personProfiles === 'identified_only') trackIdentity(posthog)
}

export function resolveConfig() {
  const env = import.meta.env
  const rate = Number(
    runtime(
      window.__IMBI_POSTHOG_REPLAY_SAMPLE_RATE__,
      env.VITE_POSTHOG_REPLAY_SAMPLE_RATE,
    ),
  )
  return {
    errorTracking: flag(
      runtime(
        window.__IMBI_POSTHOG_ERROR_TRACKING__,
        env.VITE_POSTHOG_ERROR_TRACKING,
      ),
      true,
    ),
    host:
      runtime(window.__IMBI_POSTHOG_HOST__, env.VITE_POSTHOG_HOST) ||
      'https://us.i.posthog.com',
    key: runtime(window.__IMBI_POSTHOG_KEY__, env.VITE_POSTHOG_KEY),
    personProfiles:
      runtime(
        window.__IMBI_POSTHOG_PERSON_PROFILES__,
        env.VITE_POSTHOG_PERSON_PROFILES,
      ) === 'identified_only'
        ? ('identified_only' as const)
        : ('never' as const),
    replaySampleRate:
      Number.isFinite(rate) && rate >= 0 && rate <= 1 ? rate : 1,
    sessionReplay: flag(
      runtime(
        window.__IMBI_POSTHOG_SESSION_REPLAY__,
        env.VITE_POSTHOG_SESSION_REPLAY,
      ),
      false,
    ),
    webAnalytics: flag(
      runtime(
        window.__IMBI_POSTHOG_WEB_ANALYTICS__,
        env.VITE_POSTHOG_WEB_ANALYTICS,
      ),
      false,
    ),
  }
}

// Query strings and fragments can hold OAuth codes and tokens: drop them
// from every URL property (`$current_url`, `$referrer`,
// `$initial_current_url`, ...), in the event and in its person updates.
export function stripQueryStrings(event: CaptureResult | null) {
  if (!event) return event
  for (const properties of [event.properties, event.$set, event.$set_once]) {
    for (const [name, value] of Object.entries(properties ?? {})) {
      if (
        typeof value === 'string' &&
        /(url|referrer)$/i.test(name) &&
        /[?#]/.test(value)
      ) {
        properties![name] = value.split(/[?#]/)[0]
      }
    }
  }
  return event
}

function flag(value: string | undefined, fallback: boolean): boolean {
  const v = value?.trim().toLowerCase()
  if (!v) return fallback
  return ['1', 'on', 'true', 'yes'].includes(v)
}

// Caddy writes the VITE_POSTHOG_* values into index.html at request time.
// Without a templater the placeholder arrives literally; fall back to the
// build-time value.
function runtime(
  value: string | undefined,
  fallback: string | undefined,
): string | undefined {
  return value && !value.includes('{{') ? value : fallback
}

function trackIdentity(posthog: PostHog): void {
  // undefined = not synced yet, so the first sync also clears an identity
  // that the SDK restored from persistence after a sign-out.
  let current: null | string | undefined
  const sync = () => {
    const subject = useAuthStore.getState().getUsername()
    if (subject === current) return
    current = subject
    if (!subject) {
      // Reset only an identified user, to keep one anonymous ID.
      if (posthog.get_property('$user_state') === 'identified') {
        posthog.reset()
      }
      return
    }
    void distinctId(subject).then((id) => {
      // The email local part names the person; the full email stays out.
      if (current === subject) {
        posthog.identify(id, { name: subject.split('@')[0] })
      }
    })
  }
  sync()
  useAuthStore.subscribe(sync)
}
