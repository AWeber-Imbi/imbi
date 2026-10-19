import { useEffect, useRef, useState } from 'react'

import { ArrowUp, CircleCheck, Sparkles, Square } from 'lucide-react'
import { useShallow } from 'zustand/react/shallow'

import { Button } from '@/components/ui/button'
import { SkText } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { stopAssistant, useAssistantChat } from '@/hooks/useAssistantChat'
import { cn } from '@/lib/utils'
import { useAssistantStore } from '@/stores/assistantStore'

import { ImbiMark, SessionEntry } from './MessageBubble'
import { toolLabel } from './toolLabels'
import { ToolUseIndicator } from './ToolUseIndicator'

/** Message box with send and stop. Enter sends, Shift+Enter adds a line. */
export function AssistantComposer({
  autoFocus = false,
  placeholder = 'Ask about projects, deployments, or docs…',
}: {
  autoFocus?: boolean
  placeholder?: string
}) {
  const { send } = useAssistantChat()
  const isStreaming = useAssistantStore((s) => s.isStreaming)
  const [input, setInput] = useState('')

  const submit = () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    void send(text)
  }

  return (
    <form
      className="border-tertiary focus-within:border-secondary bg-primary rounded-lg border p-2"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <Textarea
        aria-label="Message the assistant"
        autoFocus={autoFocus}
        className="min-h-16 resize-none border-0 bg-transparent p-1 shadow-none focus-visible:ring-0"
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            submit()
          }
        }}
        placeholder={placeholder}
        value={input}
      />
      <div className="flex items-center justify-end gap-2">
        <span className="text-tertiary text-xs">↵ send · ⇧↵ new line</span>
        {isStreaming ? (
          <Button
            aria-label="Stop generating"
            onClick={stopAssistant}
            size="icon"
            type="button"
            variant="outline"
          >
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button
            aria-label="Send"
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={!input.trim()}
            size="icon"
            type="submit"
          >
            <ArrowUp className="size-4" />
          </Button>
        )}
      </div>
    </form>
  )
}

/** The scrolling message list, shared by the side panel and full page. */
export function AssistantThread({ className }: { className?: string }) {
  const { retry } = useAssistantChat()
  const scrollRef = useRef<HTMLDivElement>(null)
  // useShallow re-renders only when a listed field changes; the store
  // ticks on every SSE chunk.
  const { activeToolUse, isStreaming, messages, streamingContent } =
    useAssistantStore(
      useShallow((s) => ({
        activeToolUse: s.activeToolUse,
        isStreaming: s.isStreaming,
        messages: s.messages,
        streamingContent: s.streamingContent,
      })),
    )

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, streamingContent, activeToolUse])

  return (
    <div
      className={cn('min-h-0 flex-1 overflow-y-auto', className)}
      ref={scrollRef}
    >
      {messages.length === 0 && !isStreaming ? (
        <div className="text-tertiary flex h-full flex-col items-center justify-center gap-2 text-sm">
          <Sparkles className="size-5" />
          Ask about projects, deployments or documents.
        </div>
      ) : (
        <div className="space-y-4">
          {messages.map((message, index) => (
            <div key={message.id}>
              {message.toolUse && <ToolCalls names={message.toolUse} />}
              {message.content && (
                <SessionEntry
                  content={message.content}
                  // Only the trailing assistant message marks the
                  // conversation's resting point.
                  isLatest={!isStreaming && index === messages.length - 1}
                  onRetry={
                    message.role === 'assistant'
                      ? () => retry(message.id)
                      : undefined
                  }
                  role={message.role}
                  showActions
                />
              )}
            </div>
          ))}
          {isStreaming && (
            <>
              {!activeToolUse && !streamingContent && <ThinkingNotes />}
              {activeToolUse && (
                <ToolUseIndicator toolName={activeToolUse.name} />
              )}
              {streamingContent && (
                <SessionEntry content={streamingContent} role="assistant" />
              )}
              <ImbiMark pulse />
            </>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Pre-first-token "thinking" placeholder, shown only in the streaming gap
 * before any tool call or text token arrives.
 */
function ThinkingNotes() {
  return (
    <div className="border-amber-border border-l-2 pl-4">
      <div className="text-amber-text mb-2 flex items-center gap-1.5 font-mono text-xs">
        <Sparkles className="size-3" />
        Imbi Assistant is thinking…
      </div>
      <SkText ai widths={['90%', '96%', '72%']} />
    </div>
  )
}

/** The completed tool calls of one assistant turn. */
function ToolCalls({ names }: { names: { id: string; name: string }[] }) {
  return (
    <ul className="text-tertiary mb-2 space-y-1 text-xs">
      {names.map((t) => (
        <li className="flex items-center gap-1.5" key={t.id}>
          <CircleCheck className="size-3.5" />
          {toolLabel(t.name)}
        </li>
      ))}
    </ul>
  )
}
