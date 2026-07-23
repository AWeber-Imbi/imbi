import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'

import { useDocumentPresence } from '../useDocumentPresence'

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

let qc: QueryClient

describe('useDocumentPresence', () => {
  beforeEach(() => {
    qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    vi.restoreAllMocks()
  })

  it('heartbeats while editing and filters self from the response', async () => {
    const heartbeat = vi
      .spyOn(endpoints, 'heartbeatDocumentEditing')
      .mockResolvedValue({
        editors: ['bob@example.com', 'me@example.com'],
        ttl_seconds: 30,
      })
    const { result } = renderHook(
      () => useDocumentPresence('acme', 'doc-1', 'me@example.com'),
      { wrapper: wrapper(qc) },
    )
    await waitFor(() =>
      expect(result.current.otherEditors).toEqual(['bob@example.com']),
    )
    expect(heartbeat).toHaveBeenCalledWith('acme', 'doc-1')
  })

  it('clears the editing marker on unmount', async () => {
    vi.spyOn(endpoints, 'heartbeatDocumentEditing').mockResolvedValue({
      editors: ['me@example.com'],
      ttl_seconds: 30,
    })
    const clear = vi
      .spyOn(endpoints, 'clearDocumentEditing')
      .mockResolvedValue(undefined)
    const { result, unmount } = renderHook(
      () => useDocumentPresence('acme', 'doc-1', 'me@example.com'),
      { wrapper: wrapper(qc) },
    )
    await waitFor(() => expect(result.current.otherEditors).toEqual([]))
    unmount()
    expect(clear).toHaveBeenCalledWith('acme', 'doc-1')
  })

  it('is inert without a document id — no requests at all', () => {
    const heartbeat = vi.spyOn(endpoints, 'heartbeatDocumentEditing')
    const clear = vi.spyOn(endpoints, 'clearDocumentEditing')
    const { result, unmount } = renderHook(
      () => useDocumentPresence('acme', null, 'me@example.com'),
      { wrapper: wrapper(qc) },
    )
    expect(result.current.otherEditors).toEqual([])
    unmount()
    expect(heartbeat).not.toHaveBeenCalled()
    expect(clear).not.toHaveBeenCalled()
  })
})
