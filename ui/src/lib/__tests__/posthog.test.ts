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
  default: { identify: vi.fn(), init: vi.fn(), reset: vi.fn() },
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
})

describe('stripQueryStrings', () => {
  it('removes query strings and fragments from URL properties', () => {
    const event = {
      event: '$pageview',
      properties: {
        $current_url: 'https://imbi/oauth/callback?code=secret#x',
        $referrer: 'https://idp/login?token=abc',
        other: 'keep?this',
      },
      uuid: '1',
    } as unknown as CaptureResult
    expect(stripQueryStrings(event)?.properties).toEqual({
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
