import { useAuthStore } from '@/stores/authStore'
import type {
  Conversation,
  ConversationWithMessages,
  CreateConversationRequest,
  UpdateConversationRequest,
} from '@/types/assistant'

const ASSISTANT_BASE_URL = '/assistant'

async function assistantFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = useAuthStore.getState().accessToken
  const response = await fetch(`${ASSISTANT_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) {
    if (response.status === 401) {
      window.location.assign('/login')
    }
    throw new Error(`HTTP ${response.status}`)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

// REST endpoints
export const createConversation = (data?: CreateConversationRequest) =>
  assistantFetch<Conversation>('/conversations', {
    method: 'POST',
    body: JSON.stringify(data ?? {}),
  })

export const listConversations = (params?: {
  limit?: number
  offset?: number
  include_archived?: boolean
}) => {
  const searchParams = params
    ? '?' + new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)]),
      ).toString()
    : ''
  return assistantFetch<Conversation[]>(`/conversations${searchParams}`)
}

export const getConversation = (id: string) =>
  assistantFetch<ConversationWithMessages>(`/conversations/${id}`)

export const deleteConversation = (id: string) =>
  assistantFetch<void>(`/conversations/${id}`, { method: 'DELETE' })

export const updateConversation = (
  id: string,
  data: UpdateConversationRequest,
) =>
  assistantFetch<Conversation>(`/conversations/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })

// SSE streaming via native fetch (Axios doesn't support streaming)
export type SSEEventHandler = {
  onText?: (text: string) => void
  onToolUseStart?: (id: string, name: string) => void
  onToolInput?: (partialJson: string) => void
  onContentBlockStop?: () => void
  onClientAction?: (
    action: string,
    params: Record<string, string>,
  ) => void
  onDone?: (
    messageId: string,
    usage: { input_tokens: number; output_tokens: number },
  ) => void
  onError?: (message: string) => void
}

export async function sendMessageSSE(
  conversationId: string,
  content: string,
  handlers: SSEEventHandler,
  signal?: AbortSignal,
): Promise<void> {
  const token = useAuthStore.getState().accessToken
  const url =
    `${ASSISTANT_BASE_URL}/conversations/` +
    `${conversationId}/messages`

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content }),
    signal,
  })

  if (!response.ok) {
    if (response.status === 401) {
      window.location.assign('/login')
      return
    }
    const errorText = await response.text()
    handlers.onError?.(errorText || `HTTP ${response.status}`)
    return
  }

  const reader = response.body?.getReader()
  if (!reader) {
    handlers.onError?.('No response body')
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() ?? ''

      for (const chunk of chunks) {
        const lines = chunk.split('\n')
        const eventLine = lines.find((l) =>
          l.startsWith('event: '),
        )
        const currentEvent =
          eventLine?.slice(7).trim() ?? ''
        const data = lines
          .filter((l) => l.startsWith('data: '))
          .map((l) => l.slice(6))
          .join('\n')
        if (!data) continue
        try {
          const parsed = JSON.parse(data)
          switch (currentEvent) {
            case 'text':
              handlers.onText?.(parsed.text)
              break
            case 'tool_use_start':
              handlers.onToolUseStart?.(
                parsed.id,
                parsed.name,
              )
              break
            case 'tool_input':
              handlers.onToolInput?.(parsed.partial_json)
              break
            case 'content_block_stop':
              handlers.onContentBlockStop?.()
              break
            case 'done':
              handlers.onDone?.(
                parsed.message_id,
                parsed.usage,
              )
              break
            case 'client_action':
              handlers.onClientAction?.(
                parsed.action,
                parsed.params,
              )
              break
            case 'error':
              handlers.onError?.(parsed.message)
              break
          }
        } catch {
          // Skip unparseable event payload
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
