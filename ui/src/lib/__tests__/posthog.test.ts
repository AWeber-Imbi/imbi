import { createHash } from 'node:crypto'
import posthog, { type CaptureResult } from 'posthog-js'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  distinctId,
  initPostHog,
  resolveConfig,
  stripQueryStrings,
} from '../posthog'

vi.mock('posthog-js', () => ({
  default: {
    get_property: vi.fn(),
    identify: vi.fn(),
    init: vi.fn(),
    reset: vi.fn(),
  },
}))

afterEach(() => {
  delete window.__IMBI_POSTHOG_KEY__
  delete window.__IMBI_POSTHOG_WEB_ANALYTICS__
  delete window.__IMBI_POSTHOG_SESSION_REPLAY__
  delete window.__IMBI_POSTHOG_REPLAY_SAMPLE_RATE__
  vi.clearAllMocks()
})

describe('resolveConfig', () => {
  it('defaults to error tracking only', () => {
    window.__IMBI_POSTHOG_KEY__ = 'phc_x'
    expect(resolveConfig()).toMatchObject({
      errorTracking: true,
      key: 'phc_x',
      personProfiles: 'never',
      replaySampleRate: 1,
      sessionReplay: false,
      webAnalytics: false,
    })
  })

  it('ignores an unrendered Caddy placeholder', () => {
    window.__IMBI_POSTHOG_KEY__ = '{{env "VITE_POSTHOG_KEY"}}'
    expect(resolveConfig().key).toBeUndefined()
  })

  it('rejects a sample rate outside 0 to 1', () => {
    window.__IMBI_POSTHOG_REPLAY_SAMPLE_RATE__ = '5'
    expect(resolveConfig().replaySampleRate).toBe(1)
  })
})

describe('initPostHog', () => {
  it('does nothing without a key', async () => {
    await initPostHog()
    expect(posthog.init).not.toHaveBeenCalled()
  })

  it('keeps analytics and replay off by default, always masks', async () => {
    window.__IMBI_POSTHOG_KEY__ = 'phc_x'
    await initPostHog()
    const options = vi.mocked(posthog.init).mock.calls[0][1]
    expect(options).toMatchObject({
      autocapture: false,
      capture_exceptions: true,
      capture_pageleave: false,
      capture_pageview: false,
      disable_session_recording: true,
      person_profiles: 'never',
      session_recording: {
        blockSelector: '[data-ph-no-capture]',
        maskAllInputs: true,
        maskTextSelector: '*',
      },
    })
  })

  it('turns on web analytics and replay from their switches', async () => {
    window.__IMBI_POSTHOG_KEY__ = 'phc_x'
    window.__IMBI_POSTHOG_WEB_ANALYTICS__ = 'true'
    window.__IMBI_POSTHOG_SESSION_REPLAY__ = 'true'
    await initPostHog()
    const options = vi.mocked(posthog.init).mock.calls[0][1]
    expect(options).toMatchObject({
      autocapture: false,
      capture_pageleave: true,
      capture_pageview: 'history_change',
      capture_performance: { web_vitals: true },
      disable_session_recording: false,
      session_recording: {
        blockSelector: '[data-ph-no-capture]',
        maskAllInputs: true,
        maskTextSelector: '*',
      },
    })
  })

  it('removes the query from recorded request URLs', async () => {
    window.__IMBI_POSTHOG_KEY__ = 'phc_x'
    await initPostHog()
    const mask = vi.mocked(posthog.init).mock.calls[0][1]?.session_recording
      ?.maskCapturedNetworkRequestFn
    const request = { name: 'https://imbi/cb?code=secret#x' }
    expect(mask?.(request as never)?.name).toBe('https://imbi/cb')
  })

  it('clears a restored identity when nobody is signed in', async () => {
    window.__IMBI_POSTHOG_KEY__ = 'phc_x'
    window.__IMBI_POSTHOG_PERSON_PROFILES__ = 'identified_only'
    vi.mocked(posthog.get_property).mockReturnValue('identified')
    await initPostHog()
    delete window.__IMBI_POSTHOG_PERSON_PROFILES__
    expect(posthog.reset).toHaveBeenCalledOnce()
  })

  it('keeps the anonymous identity when nobody is signed in', async () => {
    window.__IMBI_POSTHOG_KEY__ = 'phc_x'
    window.__IMBI_POSTHOG_PERSON_PROFILES__ = 'identified_only'
    vi.mocked(posthog.get_property).mockReturnValue('anonymous')
    await initPostHog()
    delete window.__IMBI_POSTHOG_PERSON_PROFILES__
    expect(posthog.reset).not.toHaveBeenCalled()
  })
})

describe('initPostHog with a token in the URL', () => {
  afterEach(() => {
    window.history.replaceState({}, '', '/')
    vi.useRealTimers()
  })

  it('waits until the OAuth callback removes the token', async () => {
    vi.useFakeTimers()
    window.__IMBI_POSTHOG_KEY__ = 'phc_x'
    window.history.replaceState({}, '', '/auth/callback#access_token=secret')
    const done = initPostHog()
    await vi.advanceTimersByTimeAsync(500)
    expect(posthog.init).not.toHaveBeenCalled()
    window.history.replaceState({}, '', '/auth/callback')
    await vi.advanceTimersByTimeAsync(200)
    await done
    expect(posthog.init).toHaveBeenCalledOnce()
  })
})

describe('stripQueryStrings', () => {
  it('removes query strings and fragments from URL properties', () => {
    const event = {
      $set_once: { $initial_current_url: 'https://imbi/x#access_token=t' },
      event: '$pageview',
      properties: {
        $current_url: 'https://imbi/oauth/callback?code=secret#x',
        $referrer: 'https://idp/login?token=abc',
        other: 'keep?this',
      },
      uuid: '1',
    } as unknown as CaptureResult
    const result = stripQueryStrings(event)
    expect(result?.$set_once).toEqual({
      $initial_current_url: 'https://imbi/x',
    })
    expect(result?.properties).toEqual({
      $current_url: 'https://imbi/oauth/callback',
      $referrer: 'https://idp/login',
      other: 'keep?this',
    })
  })
})

describe('distinctId', () => {
  it('matches the backend hash of the lower-cased subject', async () => {
    const expected = createHash('sha256').update('a@b.c').digest('hex')
    expect(await distinctId(' A@B.c ')).toBe(expected)
  })
})
