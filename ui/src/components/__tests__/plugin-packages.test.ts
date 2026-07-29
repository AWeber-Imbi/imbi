import { describe, expect, it } from 'vitest'

import { identityIntegrations } from '@/components/plugin-packages'
import type { Integration } from '@/types'

const integration = (over: Partial<Integration>): Integration =>
  ({
    capabilities: {},
    credential_fields: [],
    identifiers: {},
    links: {},
    name: 'x',
    options: {},
    plugin: 'x',
    slug: 'x',
    status: 'active',
    ...over,
  }) as unknown as Integration

describe('identityIntegrations', () => {
  it('includes only integrations with identity capability enabled', () => {
    const result = identityIntegrations([
      integration({
        capabilities: { identity: { enabled: true, options: {} } },
        plugin: 'github',
        slug: 'github',
      }),
      // identity present but disabled — not connectable
      integration({
        capabilities: { identity: { enabled: false, options: {} } },
        plugin: 'aws',
        slug: 'aws',
      }),
      // no identity capability at all
      integration({
        capabilities: { analysis: { enabled: true, options: {} } },
        plugin: 'sonarqube',
        slug: 'sonarqube',
      }),
    ])
    expect(result.map((i) => i.slug)).toEqual(['github'])
  })

  // The two-integrations-of-one-plugin regression is guarded on the hook that
  // does the join (hooks/__tests__/useConnectableIdentities.test.tsx) — that's
  // where the collapse-by-plugin-slug bug actually lived.

  it('is empty for no integrations', () => {
    expect(identityIntegrations([])).toEqual([])
  })
})
