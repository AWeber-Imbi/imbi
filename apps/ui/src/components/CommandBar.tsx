import { useCallback, useEffect, useRef, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronUp,
  HelpCircle,
  Search,
  Send,
  Sparkles,
  X,
} from 'lucide-react'

import {
  createConversation,
  getConversation,
  sendMessageSSE,
} from '@/api/assistant'
import { getConfidenceLabel, searchOrg, type SearchResult } from '@/api/search'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { queryClient } from '@/lib/queryClient'
import { getQueryKeysForResource } from '@/lib/queryKeys'
import { useAssistantStore } from '@/stores/assistantStore'

import { ConversationHistory } from './assistant/ConversationHistory'
import { SessionEntry } from './assistant/MessageBubble'
import { ToolUseIndicator } from './assistant/ToolUseIndicator'
import { SearchResultsPanel } from './search/SearchResultsPanel'

type TrayMode = 'assistant' | 'search'

// fallow-ignore-next-line complexity
export function CommandBar() {
  const { user } = useAuth()
  const { selectedOrganization } = useOrganization()
  const navigate = useNavigate()
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<TrayMode>('search')
  const [panelHeight, setPanelHeight] = useState(() => {
    const saved = localStorage.getItem('imbi-assistant-height')
    return saved ? Number(saved) : Math.round(window.innerHeight * 0.6)
  })
  const inputRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const dragRef = useRef<null | { startHeight: number; startY: number }>(null)
  const [unreadAssistant, setUnreadAssistant] = useState(false)

  const {
    activeToolUse,
    addMessage,
    addPendingToolUse,
    appendStreamingContent,
    clearConversation,
    currentConversationId,
    finishStreaming,
    isExpanded,
    isStreaming,
    messages,
    setActiveToolUse,
    setCurrentConversation,
    setExpanded,
    setMessages,
    startStreaming,
    streamingContent,
  } = useAssistantStore()

  // Debounced query for search (only active in search mode)
  const debouncedQuery = useDebounced(mode === 'search' ? input : '', 200)
  const orgSlug = selectedOrganization?.slug ?? null
  const [searchThreshold, setSearchThreshold] = useState(0.75)
  const [searchLimit, setSearchLimit] = useState(20)

  const { data: searchResults = [], isFetching: isSearching } = useQuery({
    enabled: !!debouncedQuery.trim() && !!orgSlug && mode === 'search',
    queryFn: ({ signal }) =>
      searchOrg(
        orgSlug!,
        debouncedQuery.trim(),
        { limit: searchLimit, threshold: searchThreshold },
        signal,
      ),
    queryKey: ['search', orgSlug, debouncedQuery, searchThreshold, searchLimit],
    staleTime: 30_000,
  })

  // Set CSS custom property so page content can avoid being hidden
  const INPUT_BAR_HEIGHT = 72
  useEffect(() => {
    const total = isExpanded ? panelHeight + INPUT_BAR_HEIGHT : INPUT_BAR_HEIGHT
    document.documentElement.style.setProperty(
      '--assistant-height',
      `${total}px`,
    )
  }, [isExpanded, panelHeight])

  // Auto-scroll to bottom on new assistant content
  useEffect(() => {
    if (isExpanded && mode === 'assistant' && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isExpanded, streamingContent, mode])

  // Focus input when panel expands
  useEffect(() => {
    if (isExpanded && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isExpanded])

  // Mark unread when messages arrive while not viewing the assistant tab
  useEffect(() => {
    if (messages.length === 0) {
      setUnreadAssistant(false)
    } else if (!(isExpanded && mode === 'assistant')) {
      setUnreadAssistant(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length])

  // Clear unread when user opens the assistant tab
  useEffect(() => {
    if (isExpanded && mode === 'assistant') {
      setUnreadAssistant(false)
    }
  }, [isExpanded, mode])

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value
      setInput(value)
      if (value && mode === 'search' && !isExpanded) {
        setExpanded(true)
      }
    },
    [mode, isExpanded, setExpanded],
  )

  const handleSelectConversation = useCallback(
    async (id: string) => {
      try {
        const conv = await getConversation(id)
        setCurrentConversation(id)
        setMessages(
          conv.messages.map((m) => ({
            content: m.content,
            id: m.id,
            role: m.role,
            timestamp: new Date(m.created_at),
            toolUse: m.tool_use?.map((t) => ({
              id: t.id,
              input: JSON.stringify(t.input),
              name: t.name,
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

  const sendAssistantMessage = useCallback(
    // fallow-ignore-next-line complexity
    async (messageContent: string, displayText: string) => {
      if (!isExpanded) setExpanded(true)

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
            content: 'Failed to start conversation. Please try again.',
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            timestamp: new Date(),
          })
          return
        }
      }

      addMessage({
        content: displayText,
        id: Date.now().toString(),
        role: 'user',
        timestamp: new Date(),
      })

      const fullContent = isNewConversation
        ? buildUserContext(user, selectedOrganization) + messageContent
        : messageContent

      startStreaming()
      const abort = new AbortController()
      abortRef.current = abort

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
              const current = useAssistantStore.getState().activeToolUse
              if (current) {
                addPendingToolUse(current)
                setActiveToolUse(null)
              }
            },
            onDone: (messageId) => {
              finishStreaming(messageId)
            },
            onError: (message) => {
              const {
                finishStreaming: finish,
                streamingContent: previousContent,
              } = useAssistantStore.getState()
              finish(Date.now().toString())
              if (!previousContent) {
                addMessage({
                  content: `Error: ${message}`,
                  id: (Date.now() + 1).toString(),
                  role: 'assistant',
                  timestamp: new Date(),
                })
              }
            },
            onText: (text) => {
              appendStreamingContent(text)
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
            onToolUseStart: (id, name) => {
              setActiveToolUse({ id, input: '', name })
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

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!input.trim()) return

      const userText = input.trim()

      if (mode === 'search') {
        // Inject top 3 search results as context, then switch to assistant
        const top3 = searchResults
          .filter((r) => getConfidenceLabel(r.distance) !== null)
          .slice(0, 3)
        const messageContent = buildSearchContext(userText, top3)
        setInput('')
        setMode('assistant')
        await sendAssistantMessage(messageContent, userText)
      } else {
        // Assistant mode: send message directly
        if (isStreaming) return
        setInput('')
        await sendAssistantMessage(userText, userText)
      }
    },
    [input, mode, searchResults, isStreaming, sendAssistantMessage],
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Escape') {
        setExpanded(false)
      }
    },
    [setExpanded],
  )

  const handleDragStart = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault()
      dragRef.current = { startHeight: panelHeight, startY: e.clientY }
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
        className={`fixed right-0 left-0 z-40 flex flex-col transition-transform duration-300 ease-out ${
          isExpanded ? 'translate-y-0' : 'translate-y-full'
        } border-border bg-secondary border-t shadow-2xl`}
        style={{ bottom: `${INPUT_BAR_HEIGHT}px`, height: `${panelHeight}px` }}
      >
        {/* Resize Handle */}
        <div
          className="group hover:bg-secondary flex h-1.5 shrink-0 cursor-ns-resize items-center justify-center transition-colors"
          onPointerDown={handleDragStart}
          onPointerMove={handleDragMove}
          onPointerUp={handleDragEnd}
        >
          <div className="bg-secondary group-hover:bg-muted-foreground/40 h-0.5 w-8 rounded-full transition-colors" />
        </div>

        {/* Panel Header with Tabs */}
        <Tabs onValueChange={(v) => setMode(v as TrayMode)} value={mode}>
          <div className="border-border bg-secondary flex h-8 shrink-0 border-b">
            <TabsList className="h-full w-auto items-center gap-4 border-b-0 bg-transparent px-3">
              <TabsTrigger
                className="flex items-center gap-1.5 font-mono text-xs"
                value="search"
              >
                <Search className="size-3" />
                Search
              </TabsTrigger>
              <TabsTrigger
                className="flex items-center gap-1.5 font-mono text-xs"
                value="assistant"
              >
                <Sparkles className="size-3" />
                Assistant
                {unreadAssistant && (
                  <span className="size-1.5 rounded-full bg-blue-500" />
                )}
              </TabsTrigger>
            </TabsList>

            {/* Right controls */}
            <div className="ml-auto flex h-full items-center gap-1 pr-2 pb-1">
              {mode === 'assistant' && (
                <>
                  <Button
                    aria-label="Help"
                    className="text-tertiary hover:bg-secondary hover:text-secondary size-auto rounded p-1"
                    onClick={() => sendAssistantMessage('help', 'help')}
                    size="icon"
                    type="button"
                    variant="ghost"
                  >
                    <HelpCircle className="size-3.5" />
                  </Button>
                  <ConversationHistory
                    currentConversationId={currentConversationId}
                    onNewConversation={handleNewConversation}
                    onSelectConversation={handleSelectConversation}
                  />
                  {messages.length > 0 && (
                    <Button
                      className="text-tertiary hover:bg-secondary hover:text-secondary h-auto rounded px-2 py-0.5 font-mono text-xs"
                      onClick={handleClearHistory}
                      variant="ghost"
                    >
                      clear
                    </Button>
                  )}
                </>
              )}
              <TooltipProvider delayDuration={400}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      aria-label="Close tray"
                      className="text-tertiary hover:bg-secondary hover:text-secondary size-auto rounded p-1"
                      onClick={() => setExpanded(false)}
                      size="icon"
                      type="button"
                      variant="ghost"
                    >
                      <X className="size-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">Close</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
          </div>
        </Tabs>

        {/* Panel Body */}
        <div className="bg-secondary min-h-0 flex-1 overflow-hidden">
          {mode === 'search' ? (
            <SearchResultsPanel
              isLoading={isSearching}
              limit={searchLimit}
              onLimitChange={setSearchLimit}
              onThresholdChange={setSearchThreshold}
              query={debouncedQuery}
              results={searchResults}
              threshold={searchThreshold}
            />
          ) : (
            <div
              className="h-full space-y-3 overflow-y-auto px-6 py-4"
              ref={scrollRef}
            >
              {messages.length === 0 && !isStreaming ? (
                <div className="h-full" />
              ) : (
                <>
                  {messages.map((message) => (
                    <SessionEntry
                      content={message.content}
                      key={message.id}
                      role={message.role}
                    />
                  ))}
                  {isStreaming && (
                    <>
                      {activeToolUse && (
                        <ToolUseIndicator toolName={activeToolUse.name} />
                      )}
                      {streamingContent && (
                        <SessionEntry
                          content={streamingContent}
                          role="assistant"
                        />
                      )}
                      {!streamingContent && !activeToolUse && (
                        <div className="text-tertiary pl-4 font-mono text-sm">
                          <span className="animate-pulse">...</span>
                        </div>
                      )}
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Command Input Bar */}
      <div className="border-border bg-card fixed right-0 bottom-0 left-0 z-50 border-t">
        {/* Tray Toggle */}
        <div className="flex justify-center">
          <Button
            aria-label={isExpanded ? 'Collapse tray' : 'Expand tray'}
            className={`border-tertiary bg-card text-tertiary hover:text-secondary -mt-3 h-auto rounded-t-md border border-b-0 px-4 py-0.5 font-mono text-xs transition-all ${isExpanded ? 'shadow-lg' : ''}`}
            onClick={() => setExpanded(!isExpanded)}
            type="button"
            variant="ghost"
          >
            {isExpanded ? (
              <ChevronDown className="size-3" />
            ) : (
              <div className="flex items-center gap-1.5">
                <ChevronUp className="size-3" />
                {unreadAssistant && (
                  <span className="size-1.5 rounded-full bg-blue-500" />
                )}
              </div>
            )}
          </Button>
        </div>

        {/* Input */}
        <form className="px-3 pt-2 pb-1.5" onSubmit={handleSubmit}>
          <div className="border-tertiary bg-tertiary focus-within:border-secondary flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors">
            <span className="text-tertiary text-sm select-none">&gt;</span>
            <input
              className="text-primary placeholder:text-muted-foreground flex-1 bg-transparent text-sm outline-none disabled:opacity-50"
              disabled={mode === 'assistant' && isStreaming}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder={
                mode === 'assistant' && isStreaming
                  ? 'waiting...'
                  : "Search projects, ask about deployments, or type 'help'..."
              }
              ref={inputRef}
              type="text"
              value={input}
            />
            {input.trim() && !(mode === 'assistant' && isStreaming) && (
              <Button
                className="text-tertiary hover:text-secondary size-auto rounded p-1 transition-colors"
                size="icon"
                type="submit"
                variant="ghost"
              >
                <Send className="size-3.5" />
              </Button>
            )}
          </div>
          <div className="flex items-center justify-between px-1 pt-1">
            <span className="text-secondary text-[11px]">
              {mode === 'search'
                ? '↵ switch to assistant  esc: close'
                : '↵ send  esc: close'}
            </span>
            <span className="text-secondary flex items-center gap-1 text-[11px]">
              <Sparkles className="size-3" />
              AI-powered
            </span>
          </div>
        </form>
      </div>
    </>
  )
}

function buildSearchContext(query: string, results: SearchResult[]): string {
  if (results.length === 0) return query

  const lines = results.map((r, i) => {
    const label = getConfidenceLabel(r.distance) ?? 'Related'
    const snippet =
      r.chunk_text.length > 200
        ? r.chunk_text.slice(0, 200).trimEnd() + '…'
        : r.chunk_text
    return `${i + 1}. [${label}] ${r.node_label}: "${snippet}"`
  })

  return (
    `<search_context>\n` +
    `User searched for: "${query}"\n\n` +
    `Top results:\n${lines.join('\n')}\n` +
    `</search_context>\n\n` +
    query
  )
}

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

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}
