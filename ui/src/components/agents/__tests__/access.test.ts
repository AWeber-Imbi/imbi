import { describe, expect, it } from 'vitest'

import type { SecretGrant } from '@/components/admin/secrets/types'

import { purposeSuggestions } from '../access'

const grant = (purposes: string[]) => ({ purposes }) as SecretGrant

describe('purposeSuggestions', () => {
  it('suggests the GitHub App purposes without grants', () => {
    expect(purposeSuggestions([])).toEqual(['github_read', 'github_write'])
  })

  it('adds each purpose of the grants once, sorted', () => {
    expect(
      purposeSuggestions([grant(['sentry', 'npm']), grant(['npm'])]),
    ).toEqual(['github_read', 'github_write', 'npm', 'sentry'])
  })

  it('leaves out the setup and retired purposes', () => {
    expect(
      purposeSuggestions([
        grant(['model_inference', 'workspace_checkout']),
        grant(['marketplace_fetch', 'mcp_server', 'npm']),
      ]),
    ).toEqual(['github_read', 'github_write', 'npm'])
  })
})
