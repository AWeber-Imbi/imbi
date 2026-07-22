import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { PluginOpsLogTemplates } from '@/api/endpoints'

import { usePluginOpsLogTemplates } from '../usePluginOpsLogTemplates'

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

let qc: QueryClient

function mountWithPlugins(plugins: PluginOpsLogTemplates[]) {
  vi.spyOn(endpoints, 'listPluginOpsLogTemplates').mockResolvedValue(plugins)
  const { result } = renderHook(() => usePluginOpsLogTemplates(), {
    wrapper: wrapper(qc),
  })
  return result
}

async function settle(result: { current: { isLoading: boolean } }) {
  await waitFor(() => expect(result.current.isLoading).toBe(false))
}

describe('usePluginOpsLogTemplates', () => {
  beforeEach(() => {
    qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    vi.clearAllMocks()
  })

  it('returns an empty-map fallback while loading', () => {
    vi.spyOn(endpoints, 'listPluginOpsLogTemplates').mockReturnValue(
      // Never resolve so the hook stays loading.
      new Promise(() => {}),
    )
    const { result } = renderHook(() => usePluginOpsLogTemplates(), {
      wrapper: wrapper(qc),
    })
    expect(result.current.isLoading).toBe(true)
    expect(result.current.templates.get('aws-ssm', 'deploy')).toBeUndefined()
  })

  it('returns templates indexed by plugin slug and action', async () => {
    const result = mountWithPlugins([
      {
        name: 'AWS SSM',
        slug: 'aws-ssm',
        templates: {
          set: { label: 'set {{key}}' },
          unset: { label: 'unset {{key}}' },
        },
      },
      {
        name: 'GitHub',
        slug: 'github',
        templates: { '': { label: 'pushed to {{environment}}' } },
      },
    ])
    await settle(result)
    expect(result.current.templates.get('aws-ssm', 'set')).toEqual({
      label: 'set {{key}}',
    })
    expect(result.current.templates.get('aws-ssm', 'unset')).toEqual({
      label: 'unset {{key}}',
    })
  })

  it('falls back to the empty-string action when no action matches', async () => {
    const result = mountWithPlugins([
      {
        name: 'GitHub',
        slug: 'github',
        templates: { '': { label: 'default fallback' } },
      },
    ])
    await settle(result)
    expect(result.current.templates.get('github', 'no-such-action')).toEqual({
      label: 'default fallback',
    })
    // No action key at all also resolves to the empty-action fallback.
    expect(result.current.templates.get('github', undefined)).toEqual({
      label: 'default fallback',
    })
  })

  it('returns undefined for unknown plugin slugs', async () => {
    const result = mountWithPlugins([
      { name: 'AWS SSM', slug: 'aws-ssm', templates: { set: { label: 's' } } },
    ])
    await settle(result)
    expect(result.current.templates.get('unknown', 'set')).toBeUndefined()
    // Empty slug also yields undefined (no lookup performed).
    expect(result.current.templates.get('', 'set')).toBeUndefined()
  })

  it('returns undefined for plugins with no template entries', async () => {
    const result = mountWithPlugins([
      { name: 'Empty', slug: 'empty', templates: undefined as never },
    ])
    await settle(result)
    expect(result.current.templates.get('empty', 'any')).toBeUndefined()
  })

  it('drops plugins without a slug from the index', async () => {
    const result = mountWithPlugins([
      {
        name: 'No Slug',
        slug: '' as never,
        templates: { set: { label: 's' } },
      },
      { name: 'AWS SSM', slug: 'aws-ssm', templates: { set: { label: 'a' } } },
    ])
    await settle(result)
    expect(result.current.templates.get('aws-ssm', 'set')).toEqual({
      label: 'a',
    })
  })
})
