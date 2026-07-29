import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { Integration, PluginPackage } from '@/types'

import { useConnectableIdentities } from '../useConnectableIdentities'

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

const identityPlugin = (slug: string, name: string): PluginPackage =>
  ({
    capabilities: [{ hints: {}, kind: 'identity' }],
    enabled: true,
    name,
    slug,
  }) as unknown as PluginPackage

const identityIntegration = (over: Partial<Integration>): Integration =>
  ({
    capabilities: { identity: { enabled: true, options: {} } },
    credential_fields: [],
    identifiers: {},
    links: {},
    options: {},
    status: 'active',
    ...over,
  }) as unknown as Integration

let qc: QueryClient

function mount(integrations: Integration[], plugins: PluginPackage[]) {
  vi.spyOn(endpoints, 'listIntegrations').mockResolvedValue(integrations)
  vi.spyOn(endpoints, 'listPluginPackages').mockResolvedValue(plugins)
  const { result } = renderHook(() => useConnectableIdentities('aweber'), {
    wrapper: wrapper(qc),
  })
  return result
}

describe('useConnectableIdentities', () => {
  beforeEach(() => {
    qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.clearAllMocks()
  })

  // Regression: the connections surfaces used to key off the plugin slug, so
  // a second integration of the same plugin (github.com alongside a GHEC
  // host) was collapsed away and became unreachable.
  it('returns one entry per integration when a plugin has several', async () => {
    const result = mount(
      [
        identityIntegration({
          id: 'AeYITqrf',
          name: 'GitHub',
          plugin: 'github',
          slug: 'github',
        }),
        identityIntegration({
          id: 'Xxc2LuXh',
          name: 'GitHub Enterprise Cloud',
          plugin: 'github',
          slug: 'github-enterprise-cloud',
        }),
      ],
      [identityPlugin('github', 'GitHub')],
    )

    await waitFor(() => expect(result.current.connectable).toHaveLength(2))
    expect(
      result.current.connectable.map(({ integration }) => [
        integration.id,
        integration.name,
      ]),
    ).toEqual([
      ['AeYITqrf', 'GitHub'],
      ['Xxc2LuXh', 'GitHub Enterprise Cloud'],
    ])
    // Both entries resolve to the one plugin package backing them.
    for (const { plugin } of result.current.connectable) {
      expect(plugin.slug).toBe('github')
    }
  })

  it('excludes integrations whose plugin is absent or not an identity plugin', async () => {
    const result = mount(
      [
        identityIntegration({ id: '1', name: 'GitHub', plugin: 'github' }),
        // Plugin package not installed/enabled — nothing to connect against.
        identityIntegration({ id: '2', name: 'Gitlab', plugin: 'gitlab' }),
        // Installed, but the package exposes no identity capability.
        identityIntegration({ id: '3', name: 'Logz.io', plugin: 'logzio' }),
      ],
      [
        identityPlugin('github', 'GitHub'),
        {
          capabilities: [{ hints: {}, kind: 'logs' }],
          enabled: true,
          name: 'Logz.io',
          slug: 'logzio',
        } as unknown as PluginPackage,
      ],
    )

    await waitFor(() => expect(result.current.connectable).toHaveLength(1))
    expect(result.current.connectable[0].integration.id).toBe('1')
  })

  it('excludes integrations with the identity capability disabled', async () => {
    const result = mount(
      [
        identityIntegration({
          capabilities: { identity: { enabled: false, options: {} } },
          id: '1',
          name: 'GitHub',
          plugin: 'github',
        }),
      ],
      [identityPlugin('github', 'GitHub')],
    )

    await waitFor(() =>
      expect(result.current.integrationsQuery.isLoading).toBe(false),
    )
    expect(result.current.connectable).toEqual([])
  })

  it('keeps a stable array reference across re-renders', async () => {
    vi.spyOn(endpoints, 'listIntegrations').mockResolvedValue([
      identityIntegration({ id: '1', name: 'GitHub', plugin: 'github' }),
    ])
    vi.spyOn(endpoints, 'listPluginPackages').mockResolvedValue([
      identityPlugin('github', 'GitHub'),
    ])
    const { rerender, result } = renderHook(
      () => useConnectableIdentities('aweber'),
      { wrapper: wrapper(qc) },
    )
    await waitFor(() => expect(result.current.connectable).toHaveLength(1))
    const first = result.current.connectable
    rerender()
    expect(result.current.connectable).toBe(first)
  })
})
