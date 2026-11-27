import { useCallback } from 'react'

import { useNavigate } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import {
  createConversation,
  getConversation,
  getCurrentConversation,
  listConversations,
  sendMessageSSE,
  setCurrentConversation,
} from '@/api/assistant'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { queryClient } from '@/lib/queryClient'
import { getQueryKeysForResource } from '@/lib/queryKeys'
import { useAssistantStore } from '@/stores/assistantStore'
import type { Conversation, Message } from '@/types/assistant'

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
      // One organization for the whole send, even if the reader switches.
      const orgSlug = selectedOrganization?.slug
      if (store.isStreaming || !orgSlug) return
      // Streaming state reserves the one send slot before the first
      // await, so the composer cannot start a second conversation while
      // this one is being created.
      store.startStreaming()
      // A load issued before this send must not replace the new turn or
      // abort this stream.
      openRequest += 1
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
          const conv = await createConversation(orgSlug)
          if (abort.signal.aborted) return
          conversationId = conv.id
          // setState, not setCurrentConversation, which clears messages.
          useAssistantStore.setState({ currentConversationId: conv.id })
          shareCurrentConversation(orgSlug, conv.id)
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
          orgSlug,
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
  const orgSlug = useOrganization().selectedOrganization?.slug
  return useQuery({
    enabled: enabled && !!orgSlug,
    queryFn: ({ signal }) =>
      orgSlug ? listConversations(orgSlug, { limit: 100 }, signal) : [],
    queryKey: ['assistant-conversations', orgSlug],
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

export function newAssistantConversation(orgSlug: string) {
  resetConversation()
  abortController?.abort()
  abortController = null
  shareCurrentConversation(orgSlug, null)
}

/** Load a stored conversation into the store, unless it is already open. */
let openRequest = 0

export async function openAssistantConversation(orgSlug: string, id: string) {
  const store = useAssistantStore.getState()
  // Count even a reselect of the current conversation, so a load still
  // in flight cannot replace it.
  const request = ++openRequest
  // Share even a reselect, so a link to the open conversation still
  // makes it the current one in every browser.
  shareCurrentConversation(orgSlug, id)
  if (store.currentConversationId === id) return
  await loadConversation(orgSlug, id, request)
}

export function stopAssistant() {
  abortController?.abort()
  abortController = null
  // Settle the stream: keep whatever was generated so far as a message.
  useAssistantStore.getState().finishStreaming(Date.now().toString())
}

/**
 * Keep this browser on the user's current conversation: restore it on
 * load and follow switches and new turns made in other browsers. Polls
 * while `poll` is true; otherwise it checks on mount and window focus.
 */
export function useCurrentConversationSync(poll: boolean) {
  // Each organization has its own current conversation; a switch of
  // organization fetches it and opens it, or starts a new one.
  const orgSlug = useOrganization().selectedOrganization?.slug
  useQuery({
    enabled: !!orgSlug,
    // Follow here, not in an effect: the panel remounts on every page,
    // and only a real fetch (never cached data) may switch the store.
    queryFn: async ({ signal }) => {
      if (!orgSlug) return null
      // Read only after this browser's own switch has been written.
      await pendingShare
      const conv = await getCurrentConversation(orgSlug, signal)
      // A local switch cancels this poll; its answer is out of date.
      if (!signal.aborted) followCurrentConversation(orgSlug, conv)
      return conv
    },
    queryKey: [...CURRENT_KEY, orgSlug],
    refetchInterval: poll ? 5_000 : false,
    // The app defaults turn both off; returning to a browser must catch
    // up at once.
    refetchOnWindowFocus: true,
    retry: false,
    // One check per poll interval, not one per page navigation.
    staleTime: 5_000,
  })
}

const CURRENT_KEY = ['assistant-current-conversation']

// updated_at of the stored conversation the store last loaded; a newer
// value means another browser added a turn or renamed it.
let syncedUpdatedAt: null | string = null

// Switch writes run in order, so the last one the reader made wins.
let pendingShare: Promise<unknown> = Promise.resolve()

function followCurrentConversation(orgSlug: string, conv: Conversation | null) {
  const store = useAssistantStore.getState()
  // This browser's own stream is newer than any saved state.
  if (store.isStreaming) return
  if (!conv) {
    // Drop a restore still in flight, even when nothing is open yet.
    if (store.currentConversationId) resetConversation()
    else openRequest += 1
    return
  }
  if (
    conv.id === store.currentConversationId &&
    conv.updated_at === syncedUpdatedAt
  ) {
    // The open conversation is current again; drop a load of another
    // one that an earlier poll started.
    openRequest += 1
    return
  }
  loadConversation(orgSlug, conv.id, ++openRequest).catch((err) =>
    console.error('[Assistant] Failed to sync conversation:', err),
  )
}

async function loadConversation(orgSlug: string, id: string, request: number) {
  const conv = await getConversation(orgSlug, id)
  // A later open or a new conversation supersedes this one.
  if (request !== openRequest) return
  abortController?.abort()
  abortController = null
  const store = useAssistantStore.getState()
  if (store.currentConversationId !== id) store.setCurrentConversation(id)
  store.setMessages(toStoreMessages(conv.messages))
  syncedUpdatedAt = conv.updated_at
}

function resetConversation() {
  openRequest += 1
  useAssistantStore.getState().clearConversation()
}

function shareCurrentConversation(orgSlug: string, id: null | string) {
  // Drop a poll already in flight; it can hold the previous conversation.
  void queryClient.cancelQueries({ queryKey: CURRENT_KEY })
  pendingShare = pendingShare
    .then(() => setCurrentConversation(orgSlug, id))
    .catch((err) =>
      console.error('[Assistant] Failed to share conversation:', err),
    )
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
