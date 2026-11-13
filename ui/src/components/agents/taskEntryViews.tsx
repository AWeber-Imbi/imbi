import { type ReactNode, useState } from 'react'

import { RichMarkdown } from '@/components/ui/rich-markdown'
import { cn } from '@/lib/utils'
import type { AgentTaskEvent } from '@/types'

import { type Family, label, OUTPUT_LINES } from './toolCalls'

interface OutputProps {
  dark?: boolean
  error?: boolean
  text: string
}

export function Prose({ children }: { children: string }) {
  return (
    <div className="document-markdown max-w-[74ch] text-sm">
      <RichMarkdown deferImages>{children}</RichMarkdown>
    </div>
  )
}

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
  result,
}: {
  args: Record<string, unknown>
  argsText: null | string
  error: boolean
  family: Family
  result: string
}) {
  if (argsText != null)
    return (
      <>
        <Output text={argsText} />
        <ResultOutput error={error} result={result} />
      </>
    )
  if (family === 'shell')
    return (
      <Output
        dark
        error={error}
        text={`$ ${String(args.command ?? '')}${result ? `\n${result}` : ''}`}
      />
    )
  if (family === 'edit' && !error) return <Diff args={args} />
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
      <ResultOutput error={error} result={result} />
    </>
  )
}

/**
 * Old text above new text, for an Edit, MultiEdit, NotebookEdit, or
 * Write, cut at {@link OUTPUT_LINES} until the reader asks.
 */
function Diff({ args }: { args: Record<string, unknown> }) {
  const [all, setAll] = useState(false)
  const edits: { new_string?: unknown; old_string?: unknown }[] = Array.isArray(
    args.edits,
  )
    ? (args.edits as { new_string?: unknown; old_string?: unknown }[])
    : [
        {
          new_string: args.new_string ?? args.content ?? args.new_source,
          old_string: args.old_string,
        },
      ]
  const lines = (v: unknown) => (typeof v === 'string' ? v.split('\n') : [])
  const rows: { className: string; key: string; text: string }[] = []
  edits.forEach((edit, i) => {
    if (i > 0)
      rows.push({ className: 'text-tertiary', key: `s${i}`, text: '⋯' })
    lines(edit.old_string).forEach((l, j) =>
      rows.push({
        className: 'bg-danger text-danger',
        key: `o${i}-${j}`,
        text: `- ${l}`,
      }),
    )
    lines(edit.new_string).forEach((l, j) =>
      rows.push({
        className: 'bg-success text-success',
        key: `n${i}-${j}`,
        text: `+ ${l}`,
      }),
    )
  })
  const cut = !all && rows.length > OUTPUT_LINES
  return (
    <>
      <div className="border-tertiary overflow-x-auto rounded-md border">
        <div className="bg-secondary text-secondary px-3 py-1.5 font-mono text-xs">
          {String(args.file_path ?? args.notebook_path ?? '')}
        </div>
        <pre className="py-1 font-mono text-xs leading-relaxed whitespace-pre-wrap">
          {(cut ? rows.slice(0, OUTPUT_LINES) : rows).map((row) => (
            <span className={cn('block px-3', row.className)} key={row.key}>
              {row.text}
            </span>
          ))}
        </pre>
      </div>
      {cut && <ShowAll count={rows.length} onClick={() => setAll(true)} />}
    </>
  )
}

/** Output text, cut at {@link OUTPUT_LINES} until the reader asks. */
function Output({ dark, error, text }: OutputProps) {
  const [all, setAll] = useState(false)
  const lines = text.split('\n')
  const cut = !all && lines.length > OUTPUT_LINES
  return (
    <>
      <Pane dark={dark}>
        <span
          className={cn(
            error && (dark ? 'text-terminal-danger' : 'text-danger'),
          )}
        >
          {cut ? lines.slice(0, OUTPUT_LINES).join('\n') : text}
        </span>
      </Pane>
      {cut && <ShowAll count={lines.length} onClick={() => setAll(true)} />}
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
function ResultOutput({ error, result }: { error: boolean; result: string }) {
  if (!result) return null
  return (
    <>
      <span className="text-tertiary text-[10.5px] font-semibold tracking-wide uppercase">
        Output
      </span>
      <Output error={error} text={result} />
    </>
  )
}

function ShowAll({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <button
      className="text-info self-start text-xs hover:underline"
      onClick={onClick}
      type="button"
    >
      Show all {count} lines
    </button>
  )
}
