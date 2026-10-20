import { useCallback } from 'react'

import { useNavigate } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import {
  createConversation,
  getConversation,
  listConversations,
  sendMessageSSE,
} from '@/api/assistant'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { queryClient } from '@/lib/queryClient'
import { getQueryKeysForResource } from '@/lib/queryKeys'
import { useAssistantStore } from '@/stores/assistantStore'
import type { Message } from '@/types/assistant'

// Shared sending, retry, stop and load logic for the assistant side panel
// and the full-page assistant. Both views read one store, so a
// conversation moves between them without a reload.
export function useAssistantChat() {
  const { user } = useAuth()
  const { selectedOrganization } = useOrganization()
  const navigate = useNavigate()

  const send = useCallback(
    // fallow-ignore-next-line complexity
    async (messageContent: string, displayText = messageContent) => {
      const store = useAssistantStore.getState()
      if (store.isStreaming) return
      // Streaming state reserves the one send slot before the first
      // await, so the composer cannot start a second conversation while
      // this one is being created.
      store.startStreaming()
      // Stop, New conversation and opening another conversation abort
      // this controller, including during the create below.
      const abort = new AbortController()
      abortController = abort
      store.addMessage({
        content: displayText,
        id: Date.now().toString(),
        role: 'user',
        timestamp: new Date(),
      })
      let conversationId = store.currentConversationId
      const isNewConversation = !conversationId
      if (!conversationId) {
        try {
          const conv = await createConversation()
          if (abort.signal.aborted) return
          conversationId = conv.id
          // setState, not setCurrentConversation, which clears messages.
          useAssistantStore.setState({ currentConversationId: conv.id })
        } catch (err) {
          if (abort.signal.aborted) return
          console.error('[Assistant] Failed to create conversation:', err)
          const st = useAssistantStore.getState()
          st.finishStreaming(Date.now().toString())
          st.addMessage({
            content: 'Failed to start conversation. Please try again.',
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            timestamp: new Date(),
          })
          return
        }
      }

      const fullContent = isNewConversation
        ? buildUserContext(user, selectedOrganization) + messageContent
        : messageContent

      try {
        await sendMessageSSE(
          conversationId,
          fullContent,
          {
            // fallow-ignore-next-line complexity
            onClientAction: (action, params) => {
              if (action === 'navigate_to' && params.path) {
                navigate(params.path)
              } else if (action === 'refresh_data' && params.resource) {
                const keys = getQueryKeysForResource(
                  params.resource,
                  params.org_slug,
                )
                for (const key of keys) {
                  queryClient.invalidateQueries({ queryKey: key })
                }
              }
            },
            onContentBlockStop: () => {
              const st = useAssistantStore.getState()
              if (st.activeToolUse) {
                st.addPendingToolUse(st.activeToolUse)
                st.setActiveToolUse(null)
              }
            },
            onDone: (messageId) => {
              useAssistantStore.getState().finishStreaming(messageId)
              void queryClient.invalidateQueries({
                queryKey: ['assistant-conversations'],
              })
            },
            onError: (message) => {
              const st = useAssistantStore.getState()
              const previousContent = st.streamingContent
              st.finishStreaming(Date.now().toString())
              if (!previousContent) {
                st.addMessage({
                  content: `Error: ${message}`,
                  id: (Date.now() + 1).toString(),
                  role: 'assistant',
                  timestamp: new Date(),
                })
              }
            },
            onText: (text) => {
              useAssistantStore.getState().appendStreamingContent(text)
            },
            onToolInput: (partialJson) => {
              const st = useAssistantStore.getState()
              if (st.activeToolUse) {
                st.setActiveToolUse({
                  ...st.activeToolUse,
                  input: st.activeToolUse.input + partialJson,
                })
              }
            },
            onToolUseStart: (id, name) => {
              // Discard any pre-tool "thinking" narration so the final
              // answer streams in fresh rather than appended to it.
              const st = useAssistantStore.getState()
              st.clearStreamingContent()
              st.setActiveToolUse({ id, input: '', name })
            },
          },
          abort.signal,
        )
        // The stream can close without a done event (server crash, proxy
        // timeout); settle it unless Stop or a switch already did.
        const st = useAssistantStore.getState()
        if (abortController === abort && st.isStreaming) {
          st.finishStreaming(Date.now().toString())
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('[Assistant] Streaming error:', err)
          useAssistantStore.getState().finishStreaming(Date.now().toString())
        }
      } finally {
        if (abortController === abort) abortController = null
      }
    },
    [navigate, selectedOrganization, user],
  )

  const retry = useCallback(
    (assistantId: string) => {
      const { isStreaming, messages, setMessages } =
        useAssistantStore.getState()
      if (isStreaming) return
      const userIdx = precedingUserIndex(messages, assistantId)
      if (userIdx === -1) return
      const question = messages[userIdx].content
      // Drop the question, its answer, and anything after, then re-ask.
      setMessages(messages.slice(0, userIdx))
      void send(question)
    },
    [send],
  )

  return { retry, send }
}

/** The reader's recent conversations, newest first. */
export function useAssistantConversations(enabled = true) {
  return useQuery({
    enabled,
    queryFn: ({ signal }) => listConversations({ limit: 100 }, signal),
    queryKey: ['assistant-conversations'],
    staleTime: 30_000,
  })
}

// The last page outside the full-page assistant, so "Open in side panel"
// returns there rather than to another conversation.
let returnPath = '/dashboard'

export function assistantReturnPath() {
  return returnPath
}

export function rememberAssistantReturnPath(path: string) {
  returnPath = path
}

// One stream at a time across both views, so stop works from either.
let abortController: AbortController | null = null

export function newAssistantConversation() {
  openRequest += 1
  abortController?.abort()
  abortController = null
  useAssistantStore.getState().clearConversation()
}

/** Load a stored conversation into the store, unless it is already open. */
let openRequest = 0

export async function openAssistantConversation(id: string) {
  const store = useAssistantStore.getState()
  // Count even a reselect of the current conversation, so a load still
  // in flight cannot replace it.
  const request = ++openRequest
  if (store.currentConversationId === id) return
  const conv = await getConversation(id)
  // A later open or a new conversation supersedes this one.
  if (request !== openRequest) return
  abortController?.abort()
  abortController = null
  store.setCurrentConversation(conv.id)
  store.setMessages(toStoreMessages(conv.messages))
}

export function stopAssistant() {
  abortController?.abort()
  abortController = null
  // Settle the stream: keep whatever was generated so far as a message.
  useAssistantStore.getState().finishStreaming(Date.now().toString())
}

// Stored user turns carry the context blocks the client prepended; the
// reader never typed them, so strip them for display.
const CONTEXT_BLOCK = /<(context|search_context)>[\s\S]*?<\/\1>\s*/g

// fallow-ignore-next-line complexity
function buildUserContext(
  user: null | {
    display_name: string
    email: string
    is_admin?: boolean
    roles?: string[]
  },
  org: null | { name: string; slug: string },
): string {
  if (!user) return ''
  const parts: string[] = []
  parts.push(`User: ${user.display_name} (${user.email})`)
  if (user.is_admin) parts.push('Role: Administrator')
  if (user.roles?.length) parts.push(`Roles: ${user.roles.join(', ')}`)
  if (org) parts.push(`Organization: ${org.name} (${org.slug})`)
  return `<context>\n${parts.join('\n')}\n</context>\n\n`
}

/**
 * Index of the user question that produced the assistant answer with
 * `assistantId`, or -1 if either is not found.
 */
function precedingUserIndex(
  messages: { id: string; role: string }[],
  assistantId: string,
): number {
  const idx = messages.findIndex((m) => m.id === assistantId)
  if (idx === -1) return -1
  for (let i = idx - 1; i >= 0; i--) {
    if (messages[i].role === 'user') return i
  }
  return -1
}

function toStoreMessages(messages: Message[]) {
  return messages
    .filter((m) => m.content.trim() || m.tool_use?.length)
    .map((m) => ({
      content:
        m.role === 'user' ? m.content.replace(CONTEXT_BLOCK, '') : m.content,
      id: m.id,
      role: m.role,
      timestamp: new Date(m.created_at),
      toolUse: m.tool_use?.map((t) => ({
        id: t.id,
        input: JSON.stringify(t.input),
        name: t.name,
      })),
    }))
}
