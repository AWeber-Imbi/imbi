import { Check, Copy, RotateCcw } from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import logoDark from '@/assets/logo-dark.svg'
import logoLight from '@/assets/logo-light.svg'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/contexts/ThemeContext'
import { useClipboard } from '@/hooks/useClipboard'
import { cn } from '@/lib/utils'

interface MessageActionsProps {
  content: string
  onRetry?: () => void
  /**
   * Whether to render the resting Imbi mark beneath the actions. Only
   * the latest assistant message should mark the conversation's resting
   * point; older messages keep their copy/retry but drop the mark so a
   * new user turn doesn't trail an obsolete logo.
   */
  showMark?: boolean
}

interface SessionEntryProps {
  content: string
  /**
   * Whether this is the most-recent message in the conversation. When
   * true and the role is ``assistant`` with ``showActions``, the resting
   * Imbi mark is rendered beneath the actions.
   */
  isLatest?: boolean
  /** Retry handler; when provided, a retry button is shown. */
  onRetry?: () => void
  role: 'assistant' | 'user'
  /**
   * Show the finished-round affordances: the copy/retry actions and
   * (when this is also the latest message) the Imbi mark that signals
   * the round is complete. Only meaningful for the assistant role; pass
   * for completed messages, not while streaming.
   */
  showActions?: boolean
}

/**
 * The Imbi brand mark shown beneath assistant output. Pulses while the
 * assistant is working (thinking or responding) and rests static once
 * the round is complete.
 */
export function ImbiMark({ pulse = false }: { pulse?: boolean }) {
  const { isDarkMode } = useTheme()
  return (
    <img
      alt="Imbi"
      className={cn('mt-3 mb-8 size-6', pulse && 'animate-imbi-pulse')}
      src={isDarkMode ? logoDark : logoLight}
    />
  )
}

export function SessionEntry({
  content,
  isLatest = false,
  onRetry,
  role,
  showActions = false,
}: SessionEntryProps) {
  if (role === 'user') {
    return (
      <div className="text-info font-mono text-sm">
        <span className="text-tertiary select-none">{'> '}</span>
        {content}
      </div>
    )
  }

  return (
    <div className="text-sm">
      <div className="border-tertiary text-primary border-l-2 pl-4">
        <div className="document-markdown max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
          <Markdown
            components={{
              a: (props) => (
                <a {...props} rel="noopener noreferrer" target="_blank" />
              ),
            }}
            remarkPlugins={[remarkGfm]}
          >
            {content}
          </Markdown>
        </div>
      </div>
      {showActions && (
        <MessageActions
          content={content}
          onRetry={onRetry}
          showMark={isLatest}
        />
      )}
    </div>
  )
}

/** Copy/retry actions and (optionally) the resting Imbi mark. */
function MessageActions({ content, onRetry, showMark }: MessageActionsProps) {
  const { copied, copy } = useClipboard()
  return (
    <>
      <div className="mt-2 flex items-center gap-0.5">
        <Button
          aria-label="Copy message to clipboard"
          className="text-tertiary hover:text-secondary size-7 p-0"
          onClick={() => void copy(content)}
          size="sm"
          title="Copy to clipboard"
          type="button"
          variant="ghost"
        >
          {copied ? (
            <Check className="text-success size-3.5" />
          ) : (
            <Copy className="size-3.5" />
          )}
        </Button>
        {onRetry && (
          <Button
            aria-label="Retry this response"
            className="text-tertiary hover:text-secondary size-7 p-0"
            onClick={onRetry}
            size="sm"
            title="Clear answer and resubmit the question"
            type="button"
            variant="ghost"
          >
            <RotateCcw className="size-3.5" />
          </Button>
        )}
      </div>
      {showMark && <ImbiMark />}
    </>
  )
}
