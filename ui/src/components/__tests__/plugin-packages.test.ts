import { describe, expect, it } from 'vitest'

import { identityIntegrationPluginSlugs } from '@/components/plugin-packages'
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

describe('identityIntegrationPluginSlugs', () => {
  it('includes only integrations with identity capability enabled', () => {
    const slugs = identityIntegrationPluginSlugs([
      integration({
        capabilities: { identity: { enabled: true, options: {} } },
        plugin: 'github',
      }),
      // identity present but disabled — not connectable
      integration({
        capabilities: { identity: { enabled: false, options: {} } },
        plugin: 'aws',
      }),
      // no identity capability at all
      integration({
        capabilities: { analysis: { enabled: true, options: {} } },
        plugin: 'sonarqube',
      }),
    ])
    expect([...slugs]).toEqual(['github'])
  })

  it('is empty for no integrations', () => {
    expect(identityIntegrationPluginSlugs([]).size).toBe(0)
  })
})
