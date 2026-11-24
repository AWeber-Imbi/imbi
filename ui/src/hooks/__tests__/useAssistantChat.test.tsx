import React from 'react'

import { MemoryRouter } from 'react-router-dom'

import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as assistant from '@/api/assistant'
import { queryClient } from '@/lib/queryClient'
import { useAssistantStore } from '@/stores/assistantStore'

import {
  newAssistantConversation,
  openAssistantConversation,
  stopAssistant,
  useAssistantChat,
  useCurrentConversationSync,
} from '../useAssistantChat'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/assistant', () => ({
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  getCurrentConversation: vi.fn(),
  listConversations: vi.fn(),
  sendMessageSSE: vi.fn(),
  setCurrentConversation: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: null }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ user: null }) }))

describe('useAssistantChat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAssistantStore.getState().clearConversation()
  })

  it('starts one conversation when two sends race', async () => {
    let created: (v: { id: string }) => void = () => {}
    vi.mocked(assistant.createConversation).mockReturnValue(
      new Promise((resolve) => {
        created = resolve as typeof created
      }) as ReturnType<typeof assistant.createConversation>,
    )
    vi.mocked(assistant.sendMessageSSE).mockResolvedValue()
    const { result } = renderHook(() => useAssistantChat(), {
      wrapper: MemoryRouter,
    })

    const first = result.current.send('from search')
    void result.current.send('from composer')
    created({ id: 'c-1' })
    await first

    expect(assistant.createConversation).toHaveBeenCalledOnce()
    await waitFor(() => expect(assistant.sendMessageSSE).toHaveBeenCalledOnce())
    const { currentConversationId, messages } = useAssistantStore.getState()
    expect(currentConversationId).toBe('c-1')
    expect(messages.map((m) => m.content)).toEqual(['from search'])
    // Other browsers follow the new conversation.
    await waitFor(() =>
      expect(assistant.setCurrentConversation).toHaveBeenCalledWith('c-1'),
    )
  })
  it.each([
    ['Stop', stopAssistant],
    ['New conversation', newAssistantConversation],
  ])('%s during create drops the pending send', async (_, act) => {
    let created: (v: { id: string }) => void = () => {}
    vi.mocked(assistant.createConversation).mockReturnValue(
      new Promise((resolve) => {
        created = resolve as typeof created
      }) as ReturnType<typeof assistant.createConversation>,
    )
    const { result } = renderHook(() => useAssistantChat(), {
      wrapper: MemoryRouter,
    })

    const pending = result.current.send('question')
    act()
    created({ id: 'c-1' })
    await pending

    expect(assistant.sendMessageSSE).not.toHaveBeenCalled()
    expect(useAssistantStore.getState().isStreaming).toBe(false)
  })
  it('settles a stream that closes without a done event', async () => {
    useAssistantStore.getState().setCurrentConversation('c-1')
    vi.mocked(assistant.sendMessageSSE).mockImplementation(
      async (_id, _content, handlers) => {
        handlers.onText?.('partial')
      },
    )
    const { result } = renderHook(() => useAssistantChat(), {
      wrapper: MemoryRouter,
    })

    await result.current.send('question')

    const { isStreaming, messages } = useAssistantStore.getState()
    expect(isStreaming).toBe(false)
    expect(messages.map((m) => m.content)).toEqual(['question', 'partial'])
  })
})

function stored(id: string, updatedAt: string, content = 'hello') {
  return {
    created_at: updatedAt,
    id,
    is_archived: false,
    messages: [
      {
        content,
        conversation_id: id,
        created_at: updatedAt,
        id: `${id}-m`,
        role: 'user' as const,
        sequence: 0,
      },
    ],
    model: 'm',
    title: null,
    updated_at: updatedAt,
    user_email: 'me@example.com',
  }
}

function syncWrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe('useCurrentConversationSync', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    queryClient.clear()
    useAssistantStore.getState().clearConversation()
    vi.mocked(assistant.setCurrentConversation).mockResolvedValue()
  })

  it('restores the current conversation on load', async () => {
    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(
      stored('c-1', 't1'),
    )
    vi.mocked(assistant.getConversation).mockResolvedValue(stored('c-1', 't1'))
    renderHook(() => useCurrentConversationSync(false), {
      wrapper: syncWrapper,
    })

    await waitFor(() =>
      expect(useAssistantStore.getState().messages).toHaveLength(1),
    )
    expect(useAssistantStore.getState().currentConversationId).toBe('c-1')
  })

  it('follows new turns and a new conversation from another browser', async () => {
    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(
      stored('c-1', 't1'),
    )
    vi.mocked(assistant.getConversation).mockResolvedValue(stored('c-1', 't1'))
    renderHook(() => useCurrentConversationSync(false), {
      wrapper: syncWrapper,
    })
    await waitFor(() =>
      expect(useAssistantStore.getState().currentConversationId).toBe('c-1'),
    )

    // Another browser adds a turn: updated_at moves on.
    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(
      stored('c-1', 't2'),
    )
    vi.mocked(assistant.getConversation).mockResolvedValue(
      stored('c-1', 't2', 'newer'),
    )
    await queryClient.refetchQueries()
    await waitFor(() =>
      expect(useAssistantStore.getState().messages[0].content).toBe('newer'),
    )

    // Another browser starts a new conversation.
    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(null)
    await queryClient.refetchQueries()
    await waitFor(() =>
      expect(useAssistantStore.getState().currentConversationId).toBeNull(),
    )
  })

  it('shares local switches with other browsers', async () => {
    let written: () => void = () => {}
    vi.mocked(assistant.setCurrentConversation).mockReturnValueOnce(
      new Promise<void>((resolve) => {
        written = resolve
      }),
    )
    vi.mocked(assistant.getConversation).mockResolvedValue(stored('c-2', 't1'))
    await openAssistantConversation('c-2')
    newAssistantConversation()
    // The second write waits until the first one settles.
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(assistant.setCurrentConversation).toHaveBeenCalledOnce()
    written()
    await waitFor(() =>
      expect(assistant.setCurrentConversation).toHaveBeenCalledTimes(2),
    )
    expect(vi.mocked(assistant.setCurrentConversation).mock.calls).toEqual([
      ['c-2'],
      [null],
    ])
  })

  it('shares a reselect of the open conversation without a reload', async () => {
    useAssistantStore.getState().setCurrentConversation('c-1')
    await openAssistantConversation('c-1')
    await waitFor(() =>
      expect(assistant.setCurrentConversation).toHaveBeenCalledWith('c-1'),
    )
    expect(assistant.getConversation).not.toHaveBeenCalled()
  })

  it('drops a restore in flight when another browser clears', async () => {
    let loaded: (v: ReturnType<typeof stored>) => void = () => {}
    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(
      stored('c-1', 't1'),
    )
    vi.mocked(assistant.getConversation).mockReturnValue(
      new Promise((resolve) => {
        loaded = resolve
      }),
    )
    renderHook(() => useCurrentConversationSync(false), {
      wrapper: syncWrapper,
    })
    await waitFor(() => expect(assistant.getConversation).toHaveBeenCalled())

    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(null)
    await queryClient.refetchQueries()
    loaded(stored('c-1', 't1'))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(useAssistantStore.getState().currentConversationId).toBeNull()
  })

  it('drops a load in flight when a poll confirms the open conversation', async () => {
    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(
      stored('c-1', 't1'),
    )
    vi.mocked(assistant.getConversation).mockResolvedValue(stored('c-1', 't1'))
    renderHook(() => useCurrentConversationSync(false), {
      wrapper: syncWrapper,
    })
    await waitFor(() =>
      expect(useAssistantStore.getState().currentConversationId).toBe('c-1'),
    )

    // A poll switches to c-2, but its load is still pending ...
    let loaded: (v: ReturnType<typeof stored>) => void = () => {}
    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(
      stored('c-2', 't1'),
    )
    vi.mocked(assistant.getConversation).mockReturnValue(
      new Promise((resolve) => {
        loaded = resolve
      }),
    )
    await queryClient.refetchQueries()
    // ... when the next poll says c-1 is current again.
    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(
      stored('c-1', 't1'),
    )
    await queryClient.refetchQueries()
    loaded(stored('c-2', 't1'))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(useAssistantStore.getState().currentConversationId).toBe('c-1')
  })

  it('keeps a send that starts while a sync load is in flight', async () => {
    useAssistantStore.getState().setCurrentConversation('c-1')
    let loaded: (v: ReturnType<typeof stored>) => void = () => {}
    vi.mocked(assistant.getCurrentConversation).mockResolvedValue(
      stored('c-1', 'sent'),
    )
    vi.mocked(assistant.getConversation).mockReturnValue(
      new Promise((resolve) => {
        loaded = resolve
      }),
    )
    let streamed: () => void = () => {}
    vi.mocked(assistant.sendMessageSSE).mockReturnValue(
      new Promise<void>((resolve) => {
        streamed = resolve
      }),
    )
    renderHook(() => useCurrentConversationSync(false), {
      wrapper: syncWrapper,
    })
    await waitFor(() => expect(assistant.getConversation).toHaveBeenCalled())
    const { result } = renderHook(() => useAssistantChat(), {
      wrapper: MemoryRouter,
    })

    const sending = result.current.send('question')
    loaded(stored('c-1', 'sent'))
    await new Promise((resolve) => setTimeout(resolve, 0))

    const { isStreaming, messages } = useAssistantStore.getState()
    expect(isStreaming).toBe(true)
    expect(messages.map((m) => m.content)).toEqual(['question'])
    streamed()
    await sending
  })
})
