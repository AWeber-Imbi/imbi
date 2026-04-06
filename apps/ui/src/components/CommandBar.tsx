import { useState, useRef, useEffect, useCallback } from 'react'
import {
  Send,
  ChevronUp,
  ChevronDown,
  X,
  Terminal,
  HelpCircle,
  Sparkles,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAssistantStore } from '@/stores/assistantStore'
import {
  sendMessageSSE,
  createConversation,
  getConversation,
} from '@/api/assistant'
import { useAuth } from '@/hooks/useAuth'
import { useOrganization } from '@/contexts/OrganizationContext'
import { queryClient } from '@/main'
import { getQueryKeysForResource } from '@/lib/queryKeys'
import { SessionEntry } from './assistant/MessageBubble'
import { ToolUseIndicator } from './assistant/ToolUseIndicator'
import { ConversationHistory } from './assistant/ConversationHistory'

interface CommandBarProps {
  isDarkMode: boolean
}

function buildUserContext(
  user: {
    display_name: string
    email: string
    groups?: string[]
    roles?: string[]
    is_admin?: boolean
  } | null,
  org: { name: string; slug: string } | null,
): string {
  if (!user) return ''
  const parts: string[] = []
  parts.push(`User: ${user.display_name} (${user.email})`)
  if (user.is_admin) parts.push('Role: Administrator')
  if (user.groups?.length) parts.push(`Groups: ${user.groups.join(', ')}`)
  if (user.roles?.length) parts.push(`Roles: ${user.roles.join(', ')}`)
  if (org) parts.push(`Organization: ${org.name} (${org.slug})`)
  return `<context>\n${parts.join('\n')}\n</context>\n\n`
}

export function CommandBar({ isDarkMode }: CommandBarProps) {
  const { user } = useAuth()
  const { selectedOrganization } = useOrganization()
  const navigate = useNavigate()
  const [input, setInput] = useState('')
  const [panelHeight, setPanelHeight] = useState(() => {
    const saved = localStorage.getItem('imbi-assistant-height')
    return saved ? Number(saved) : Math.round(window.innerHeight * 0.6)
  })
  const inputRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null)

  const {
    isExpanded,
    setExpanded,
    currentConversationId,
    setCurrentConversation,
    messages,
    isStreaming,
    streamingContent,
    activeToolUse,
    addMessage,
    setMessages,
    startStreaming,
    appendStreamingContent,
    setActiveToolUse,
    addPendingToolUse,
    finishStreaming,
    clearConversation,
  } = useAssistantStore()

  // Set CSS custom property so page content can avoid being hidden
  const INPUT_BAR_HEIGHT = 72
  useEffect(() => {
    const total = isExpanded ? panelHeight + INPUT_BAR_HEIGHT : INPUT_BAR_HEIGHT
    document.documentElement.style.setProperty(
      '--assistant-height',
      `${total}px`,
    )
  }, [isExpanded, panelHeight])

  // Auto-scroll to bottom on new content
  useEffect(() => {
    if (isExpanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isExpanded, streamingContent])

  // Focus input when panel expands
  useEffect(() => {
    if (isExpanded && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isExpanded])

  const handleSelectConversation = useCallback(
    async (id: string) => {
      try {
        const conv = await getConversation(id)
        setCurrentConversation(id)
        setMessages(
          conv.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            timestamp: new Date(m.created_at),
            toolUse: m.tool_use?.map((t) => ({
              id: t.id,
              name: t.name,
              input: JSON.stringify(t.input),
            })),
          })),
        )
      } catch (err) {
        console.error('[Assistant] Failed to load conversation:', err)
      }
    },
    [setCurrentConversation, setMessages],
  )

  const handleNewConversation = useCallback(() => {
    clearConversation()
  }, [clearConversation])

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!input.trim() || isStreaming) return

      const userText = input.trim()
      setInput('')

      if (!isExpanded) {
        setExpanded(true)
      }

      // Create conversation if none active
      let conversationId = currentConversationId
      let isNewConversation = false
      if (!conversationId) {
        isNewConversation = true
        try {
          const conv = await createConversation()
          conversationId = conv.id
          setCurrentConversation(conv.id)
        } catch (err) {
          console.error('[Assistant] Failed to create conversation:', err)
          addMessage({
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: 'Failed to start conversation. Please try again.',
            timestamp: new Date(),
          })
          return
        }
      }

      // Add user message optimistically after conversation
      // context is set (setCurrentConversation clears messages)
      const userMessage = {
        id: Date.now().toString(),
        role: 'user' as const,
        content: userText,
        timestamp: new Date(),
      }
      addMessage(userMessage)

      // Prepend user/org context on the first message so
      // the assistant knows who is asking and which org
      // they are working in.
      const messageContent = isNewConversation
        ? buildUserContext(user, selectedOrganization) + userText
        : userText

      // Start streaming
      startStreaming()
      const abort = new AbortController()
      abortRef.current = abort

      try {
        await sendMessageSSE(
          conversationId,
          messageContent,
          {
            onText: (text) => {
              appendStreamingContent(text)
            },
            onToolUseStart: (id, name) => {
              setActiveToolUse({ id, name, input: '' })
            },
            onToolInput: (partialJson) => {
              const current = useAssistantStore.getState().activeToolUse
              if (current) {
                setActiveToolUse({
                  ...current,
                  input: current.input + partialJson,
                })
              }
            },
            onContentBlockStop: () => {
              const current = useAssistantStore.getState().activeToolUse
              if (current) {
                addPendingToolUse(current)
                setActiveToolUse(null)
              }
            },
            onClientAction: (action, params) => {
              if (action === 'navigate_to' && params.path) {
                navigate(params.path)
              } else if (action === 'refresh_data' && params.resource) {
                const keys = getQueryKeysForResource(
                  params.resource,
                  params.org_slug,
                )
                for (const key of keys) {
                  queryClient.invalidateQueries({
                    queryKey: key,
                  })
                }
              }
            },
            onDone: (messageId) => {
              finishStreaming(messageId)
            },
            onError: (message) => {
              const {
                streamingContent: previousContent,
                finishStreaming: finish,
              } = useAssistantStore.getState()
              finish(Date.now().toString())
              if (!previousContent) {
                addMessage({
                  id: (Date.now() + 1).toString(),
                  role: 'assistant',
                  content: `Error: ${message}`,
                  timestamp: new Date(),
                })
              }
            },
          },
          abort.signal,
        )
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('[Assistant] Streaming error:', err)
          finishStreaming(Date.now().toString())
        }
      } finally {
        abortRef.current = null
      }
    },
    [
      input,
      isStreaming,
      isExpanded,
      currentConversationId,
      setExpanded,
      addMessage,
      setCurrentConversation,
      user,
      selectedOrganization,
      startStreaming,
      appendStreamingContent,
      setActiveToolUse,
      addPendingToolUse,
      finishStreaming,
      navigate,
    ],
  )

  const handleDragStart = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault()
      dragRef.current = { startY: e.clientY, startHeight: panelHeight }
      ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
    },
    [panelHeight],
  )

  const handleDragMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return
    const delta = dragRef.current.startY - e.clientY
    const minH = 150
    const maxH = window.innerHeight - 120
    const newHeight = Math.min(
      maxH,
      Math.max(minH, dragRef.current.startHeight + delta),
    )
    setPanelHeight(newHeight)
  }, [])

  const handleDragEnd = useCallback(() => {
    if (!dragRef.current) return
    dragRef.current = null
    localStorage.setItem('imbi-assistant-height', String(panelHeight))
  }, [panelHeight])

  const handleClearHistory = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
    }
    clearConversation()
  }, [clearConversation])

  return (
    <>
      {/* Session Panel */}
      <div
        className={`fixed bottom-16 left-0 right-0 transition-transform duration-300 ease-out ${
          isExpanded ? 'translate-y-0' : 'translate-y-full'
        } ${
          isDarkMode
            ? 'border-gray-700 bg-gray-900'
            : 'border-gray-200 bg-gray-50'
        } border-t shadow-2xl`}
        style={{ height: `${panelHeight}px` }}
      >
        {/* Resize Handle */}
        <div
          onPointerDown={handleDragStart}
          onPointerMove={handleDragMove}
          onPointerUp={handleDragEnd}
          className={`group flex h-1.5 cursor-ns-resize items-center justify-center ${
            isDarkMode ? 'hover:bg-gray-800' : 'hover:bg-gray-200'
          } transition-colors`}
        >
          <div
            className={`h-0.5 w-8 rounded-full ${
              isDarkMode
                ? 'bg-gray-700 group-hover:bg-gray-500'
                : 'bg-gray-300 group-hover:bg-gray-400'
            } transition-colors`}
          />
        </div>
        {/* Panel Header */}
        <div
          className={`flex items-center justify-between border-b px-4 py-2 ${
            isDarkMode
              ? 'border-gray-800 bg-gray-900'
              : 'border-gray-200 bg-gray-100'
          }`}
        >
          <div className="flex items-center gap-2">
            <Terminal
              className={`h-3.5 w-3.5 ${
                isDarkMode ? 'text-gray-500' : 'text-gray-400'
              }`}
            />
            <span
              className={`font-mono text-xs ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}
            >
              imbi-assistant
            </span>
            {messages.length > 0 && (
              <span
                className={`font-mono text-xs ${
                  isDarkMode ? 'text-gray-600' : 'text-gray-400'
                }`}
              >
                ({Math.floor(messages.length / 2) || 1} exchange
                {Math.floor(messages.length / 2) !== 1 ? 's' : ''})
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => {
                setInput('help')
                inputRef.current?.focus()
              }}
              aria-label="Help"
              type="button"
              className={`rounded p-1 ${
                isDarkMode
                  ? 'text-gray-500 hover:bg-gray-800 hover:text-gray-400'
                  : 'text-gray-400 hover:bg-gray-200 hover:text-gray-600'
              }`}
            >
              <HelpCircle className="h-3.5 w-3.5" />
            </button>
            <ConversationHistory
              isDarkMode={isDarkMode}
              currentConversationId={currentConversationId}
              onSelectConversation={handleSelectConversation}
              onNewConversation={handleNewConversation}
            />
            {messages.length > 0 && (
              <button
                onClick={handleClearHistory}
                className={`rounded px-2 py-0.5 font-mono text-xs ${
                  isDarkMode
                    ? 'text-gray-500 hover:bg-gray-800 hover:text-gray-400'
                    : 'text-gray-400 hover:bg-gray-200 hover:text-gray-600'
                }`}
              >
                clear
              </button>
            )}
            <button
              onClick={() => setExpanded(false)}
              aria-label="Close assistant"
              type="button"
              className={`rounded p-1 ${
                isDarkMode
                  ? 'text-gray-500 hover:bg-gray-800 hover:text-gray-400'
                  : 'text-gray-400 hover:bg-gray-200 hover:text-gray-600'
              }`}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Session Output */}
        <div
          ref={scrollRef}
          className={`space-y-3 overflow-y-auto px-6 py-4 ${
            isDarkMode ? 'bg-gray-900' : 'bg-gray-50'
          }`}
          style={{ height: 'calc(100% - 43px)' }}
        >
          {messages.length === 0 && !isStreaming ? (
            <div className="h-full" />
          ) : (
            <>
              {messages.map((message) => (
                <SessionEntry
                  key={message.id}
                  role={message.role}
                  content={message.content}
                  isDarkMode={isDarkMode}
                />
              ))}
              {isStreaming && (
                <>
                  {activeToolUse && (
                    <ToolUseIndicator
                      toolName={activeToolUse.name}
                      isDarkMode={isDarkMode}
                    />
                  )}
                  {streamingContent && (
                    <SessionEntry
                      role="assistant"
                      content={streamingContent}
                      isDarkMode={isDarkMode}
                    />
                  )}
                  {!streamingContent && !activeToolUse && (
                    <div
                      className={`pl-4 font-mono text-sm ${
                        isDarkMode ? 'text-gray-600' : 'text-gray-400'
                      }`}
                    >
                      <span className="animate-pulse">...</span>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>

      {/* Command Input Bar */}
      <div
        className={`fixed bottom-0 left-0 right-0 z-50 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-900'
            : 'border-gray-200 bg-white'
        } border-t`}
      >
        {/* Tray Toggle */}
        <div className="flex justify-center">
          <button
            onClick={() => setExpanded(!isExpanded)}
            aria-label={isExpanded ? 'Collapse assistant' : 'Expand assistant'}
            type="button"
            className={`-mt-3 rounded-t-md border border-b-0 px-4 py-0.5 font-mono text-xs transition-all ${
              isDarkMode
                ? 'border-gray-700 bg-gray-800 text-gray-500 hover:text-gray-400'
                : 'border-gray-200 bg-white text-gray-400 hover:text-gray-600'
            } ${isExpanded ? 'shadow-lg' : ''}`}
          >
            {isExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <div className="flex items-center gap-1.5">
                <ChevronUp className="h-3 w-3" />
                {messages.length > 0 && (
                  <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
                )}
              </div>
            )}
          </button>
        </div>

        {/* Input */}
        <form onSubmit={handleSubmit} className="px-3 pb-1.5 pt-2">
          <div
            className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
              isDarkMode
                ? 'border-gray-700 bg-tertiary focus-within:border-gray-600'
                : 'border-tertiary bg-tertiary focus-within:border-secondary'
            } transition-colors`}
          >
            <span
              className={`select-none text-sm ${
                isDarkMode ? 'text-gray-500' : 'text-gray-500'
              }`}
            >
              &gt;
            </span>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                isStreaming
                  ? 'waiting...'
                  : "Search projects, ask about deployments, or type 'help'..."
              }
              disabled={isStreaming}
              className={`flex-1 bg-transparent text-sm outline-none ${
                isDarkMode
                  ? 'text-gray-200 placeholder:text-gray-500'
                  : 'text-gray-800 placeholder:text-gray-400'
              } disabled:opacity-50`}
            />
            {input.trim() && !isStreaming && (
              <button
                type="submit"
                className={`rounded p-1 transition-colors ${
                  isDarkMode
                    ? 'text-gray-400 hover:text-gray-300'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Send className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <div className="flex items-center justify-between px-1 pt-1">
            <span
              className={`text-[11px] ${
                isDarkMode ? 'text-gray-500' : 'text-secondary'
              }`}
            >
              Press Enter to send
            </span>
            <span
              className={`flex items-center gap-1 text-[11px] ${
                isDarkMode ? 'text-gray-500' : 'text-secondary'
              }`}
            >
              <Sparkles className="h-3 w-3" />
              AI-powered
            </span>
          </div>
        </form>
      </div>
    </>
  )
}
