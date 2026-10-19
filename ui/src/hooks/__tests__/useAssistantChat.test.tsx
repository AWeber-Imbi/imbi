import { MemoryRouter } from 'react-router-dom'

import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as assistant from '@/api/assistant'
import { useAssistantStore } from '@/stores/assistantStore'

import {
  newAssistantConversation,
  stopAssistant,
  useAssistantChat,
} from '../useAssistantChat'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/assistant', () => ({
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  listConversations: vi.fn(),
  sendMessageSSE: vi.fn(),
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
})
