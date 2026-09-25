import React from 'react'

import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'

import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useUrlSearchQuery } from '../useUrlSearchQuery'

function setup(url: string) {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>
  )
  return renderHook(
    () => ({
      location: useLocation(),
      navigate: useNavigate(),
      query: useUrlSearchQuery('q', 10),
    }),
    { wrapper },
  )
}

describe('useUrlSearchQuery', () => {
  it('seeds the input from the URL', () => {
    const { result } = setup('/x?q=api')
    expect(result.current.query.inputQuery).toBe('api')
    expect(result.current.query.debouncedQuery).toBe('api')
  })

  it('writes the debounced input to the URL, preserving other params', async () => {
    const { result } = setup('/x?state=open')
    act(() => result.current.query.setInputQuery('api'))
    await waitFor(() =>
      expect(result.current.location.search).toBe('?state=open&q=api'),
    )
    act(() => result.current.query.setInputQuery(''))
    await waitFor(() =>
      expect(result.current.location.search).toBe('?state=open'),
    )
  })

  it('resyncs the input on external URL changes', async () => {
    const { result } = setup('/x?q=api')
    act(() => result.current.navigate('/x?q=ui'))
    await waitFor(() => expect(result.current.query.inputQuery).toBe('ui'))
    act(() => result.current.navigate('/x'))
    await waitFor(() => expect(result.current.query.inputQuery).toBe(''))
  })

  it('does not overwrite an external URL change with the stale query', async () => {
    const { result } = setup('/x?q=api')
    act(() => result.current.navigate('/x?q=ui'))
    expect(result.current.location.search).toBe('?q=ui')
    await waitFor(() => expect(result.current.query.debouncedQuery).toBe('ui'))
    expect(result.current.location.search).toBe('?q=ui')
  })

  it('resyncs the input when navigating away and back before the debounce', async () => {
    const { result } = setup('/x?q=api')
    act(() => result.current.navigate('/x?q=ui'))
    act(() => result.current.navigate('/x?q=api'))
    expect(result.current.query.inputQuery).toBe('api')
    await act(() => new Promise((resolve) => setTimeout(resolve, 30)))
    expect(result.current.query.debouncedQuery).toBe('api')
    expect(result.current.location.search).toBe('?q=api')
  })

  it('does not clobber in-flight typing when its own URL write lands', async () => {
    const { result } = setup('/x')
    act(() => result.current.query.setInputQuery('ab'))
    await waitFor(() => expect(result.current.location.search).toBe('?q=ab'))
    act(() => result.current.query.setInputQuery('abc'))
    expect(result.current.query.inputQuery).toBe('abc')
    await waitFor(() => expect(result.current.location.search).toBe('?q=abc'))
    expect(result.current.query.inputQuery).toBe('abc')
  })
})
