import { memo, type ReactNode } from 'react'

import { RichMarkdown } from '@/components/ui/rich-markdown'
import { cn } from '@/lib/utils'
import type { AgentTaskEvent } from '@/types'

import { useTaskSearch } from './taskSearch'
import { type Family, label, OUTPUT_LINES } from './toolCalls'
import { cutAt, cutText, diffPath, diffRows, type ToolPart } from './toolText'

interface OutputProps extends Whole {
  dark?: boolean
  error?: boolean
  text: string
}

/** Whether the reader asked to see a cut part in full. */
interface Whole {
  all: boolean
  onAll: () => void
}

export const Prose = memo(function Prose({ children }: { children: string }) {
  return (
    <div className="document-markdown text-sm">
      <RichMarkdown deferImages>{children}</RichMarkdown>
    </div>
  )
})

export function Todos({ event }: { event: AgentTaskEvent }) {
  const todos = (event.payload.todos ?? []) as {
    done?: boolean
    title?: string
  }[]
  return (
    <div className="border-tertiary bg-primary inline-flex flex-col gap-1 rounded-lg border px-3 py-2">
      <span className="text-tertiary text-[10.5px] font-semibold tracking-wide uppercase">
        Plan · {todos.filter((t) => t.done).length} of {todos.length} done
      </span>
      <ul className="flex flex-col gap-0.5 text-xs">
        {todos.map((t, i) => (
          <li className={cn(t.done && 'text-tertiary line-through')} key={i}>
            <span
              className={cn(
                'inline-block w-4',
                t.done ? 'text-success' : 'text-tertiary',
              )}
            >
              {t.done ? '✓' : '○'}
            </span>
            {t.title}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ToolReadable({
  args,
  argsText,
  error,
  family,
  isWhole,
  onWhole,
  result,
}: {
  args: Record<string, unknown>
  argsText: null | string
  error: boolean
  family: Family
  isWhole: (part: ToolPart) => boolean
  onWhole: (part: ToolPart) => void
  result: string
}) {
  const whole = (part: ToolPart) => ({
    all: isWhole(part),
    onAll: () => onWhole(part),
  })
  if (argsText != null)
    return (
      <>
        <Output text={argsText} {...whole('input')} />
        <ResultOutput error={error} result={result} {...whole('output')} />
      </>
    )
  if (family === 'shell')
    return (
      <Output
        dark
        error={error}
        text={`$ ${String(args.command ?? '')}${result ? `\n${result}` : ''}`}
        {...whole('output')}
      />
    )
  if (family === 'edit' && !error)
    return <Diff args={args} {...whole('input')} />
  return (
    <>
      <Pane>
        {Object.entries(args).map(([k, v], i) => (
          <span key={k}>
            {i > 0 && '\n'}
            <span className="text-tertiary">{k}</span> {label(v)}
          </span>
        ))}
      </Pane>
      <ResultOutput error={error} result={result} {...whole('output')} />
    </>
  )
}

/**
 * Old text above new text, for an Edit, MultiEdit, NotebookEdit, or
 * Write, cut at {@link OUTPUT_LINES} until the reader asks.
 */
function Diff({ all, args, onAll }: Whole & { args: Record<string, unknown> }) {
  const rows = diffRows(args)
  const [query] = useTaskSearch()
  const cut = cutAt(
    rows.map((row) => row.text),
    all,
    query,
  )
  return (
    <>
      <div className="border-tertiary overflow-x-auto rounded-md border">
        <div className="bg-secondary text-secondary px-3 py-1.5 font-mono text-xs">
          {diffPath(args)}
        </div>
        <pre className="py-1 font-mono text-xs leading-relaxed whitespace-pre-wrap">
          {(cut ? rows.slice(0, OUTPUT_LINES) : rows).map((row) => (
            <span className={cn('block px-3', row.className)} key={row.key}>
              {row.text}
            </span>
          ))}
        </pre>
      </div>
      {cut && <ShowAll count={rows.length} onClick={onAll} />}
    </>
  )
}

/**
 * Output text, cut at {@link OUTPUT_LINES} until the reader asks, or a
 * search matches the part that is cut.
 */
function Output({ all, dark, error, onAll, text }: OutputProps) {
  const lines = text.split('\n')
  const [query] = useTaskSearch()
  const cut = cutAt(lines, all, query)
  return (
    <>
      <Pane dark={dark}>
        <span
          className={cn(
            error && (dark ? 'text-terminal-danger' : 'text-danger'),
          )}
        >
          {cut ? cutText(lines) : text}
        </span>
      </Pane>
      {cut && <ShowAll count={lines.length} onClick={onAll} />}
    </>
  )
}

function Pane({ children, dark }: { children: ReactNode; dark?: boolean }) {
  return (
    <div
      className={cn(
        'overflow-x-auto rounded-md',
        dark ? 'bg-terminal' : 'border border-tertiary bg-tertiary',
      )}
    >
      <pre
        className={cn(
          'px-3 py-2 font-mono text-xs leading-relaxed wrap-break-word whitespace-pre-wrap',
          dark && 'text-terminal',
        )}
      >
        {children}
      </pre>
    </div>
  )
}

/** The labeled output of a call, when it has one. */
function ResultOutput({
  error,
  result,
  ...whole
}: Whole & { error: boolean; result: string }) {
  if (!result) return null
  return (
    <>
      <span className="text-tertiary text-[10.5px] font-semibold tracking-wide uppercase">
        Output
      </span>
      <Output error={error} text={result} {...whole} />
    </>
  )
}

function ShowAll({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <button
      className="text-secondary hover:text-primary self-start text-xs font-medium underline-offset-2 hover:underline"
      onClick={onClick}
      type="button"
    >
      Show all {count} lines
    </button>
  )
}
