import { describe, expect, it } from 'vitest'

import type {
  SecretBinding,
  SecretGrant,
} from '@/components/admin/secrets/types'

import {
  bindingOf,
  canSupplyRunner,
  covers,
  fieldReferences,
  purposeSuggestions,
} from '../access'

const grant = (purposes: string[]) => ({ purposes }) as SecretGrant

const binding = (changes: Partial<SecretBinding> = {}) =>
  ({
    allowed_delivery_modes: ['file_descriptor'],
    allowed_fields: [],
    enabled: true,
    id: 'b-1',
    reference: 'secret://ops/token',
    ...changes,
  }) as SecretBinding

describe('canSupplyRunner', () => {
  it('accepts an enabled file_descriptor binding', () => {
    expect(canSupplyRunner(binding())).toBe(true)
  })

  it('refuses a disabled binding', () => {
    expect(canSupplyRunner(binding({ enabled: false }))).toBe(false)
  })

  it('refuses a provider key binding', () => {
    expect(
      canSupplyRunner(binding({ provider_key_usage: { host: 'x' } })),
    ).toBe(false)
  })

  it('refuses a binding that allows only environment delivery', () => {
    expect(
      canSupplyRunner(binding({ allowed_delivery_modes: ['environment'] })),
    ).toBe(false)
  })
})

describe('bindingOf', () => {
  const bindings = [binding()]

  it('finds the binding of a reference with a field', () => {
    expect(bindingOf(bindings, 'secret://ops/token#api-key')).toBe(bindings[0])
  })

  it('finds nothing for an unknown reference', () => {
    expect(bindingOf(bindings, 'secret://ops/other')).toBeUndefined()
  })
})

describe('fieldReferences', () => {
  it('offers each allowed field of a binding', () => {
    expect(
      fieldReferences([binding({ allowed_fields: ['user', 'pass'] })]),
    ).toEqual(['secret://ops/token#user', 'secret://ops/token#pass'])
  })

  it('offers the bare reference of a binding without fields', () => {
    expect(fieldReferences([binding()])).toEqual(['secret://ops/token'])
  })
})

describe('covers', () => {
  const scoped = (project_ids: string[]) =>
    ({
      binding_ids: ['b-1'],
      delivery_modes: ['file_descriptor'],
      project_ids,
      purposes: ['mcp_header'],
    }) as unknown as SecretGrant

  it('counts a grant for every project', () => {
    expect(covers([scoped([])], 'b-1', 'mcp_header', 'file_descriptor')).toBe(
      true,
    )
  })

  it('does not count a grant for some projects', () => {
    expect(
      covers([scoped(['p-1'])], 'b-1', 'mcp_header', 'file_descriptor'),
    ).toBe(false)
  })
})

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
