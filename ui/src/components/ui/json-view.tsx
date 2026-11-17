import { type ReactNode, useState } from 'react'

import { Check, ChevronRight, Copy } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useClipboard } from '@/hooks/useClipboard'
import { cn } from '@/lib/utils'

export interface JsonViewProps {
  className?: string
  data: unknown
  /** Levels open on first render; deeper objects and arrays start folded. */
  initialDepth?: number
  /** Entries an object or array shows before a "Show more" button. */
  pageSize?: number
  /** Lines a string shows before it folds behind a "Show all" button. */
  stringLines?: number
}

type Container = Record<string, unknown> | unknown[]

interface Options {
  initialDepth: number
  pageSize: number
  stringLines: number
}

const CHARS_PER_LINE = 120
const PREVIEW_CHARS = 48

const tone = {
  boolean: 'text-(--ds-text-accent)',
  key: 'text-(--ds-text-info)',
  null: 'text-(--ds-text-tertiary) italic',
  number: 'text-(--ds-text-warning)',
  punct: 'text-(--ds-text-secondary)',
  string: 'text-(--ds-text-success)',
}

export function JsonView({
  className,
  data,
  initialDepth = Infinity,
  pageSize = 100,
  stringLines = 12,
}: JsonViewProps) {
  return (
    <TooltipProvider delayDuration={300}>
      <div className={cn('font-mono text-xs leading-5', className)}>
        <Node
          depth={0}
          last
          options={{ initialDepth, pageSize, stringLines }}
          value={data}
        />
      </div>
    </TooltipProvider>
  )
}

function Branch({
  depth,
  last,
  name,
  options,
  value,
}: {
  depth: number
  last: boolean
  name?: string
  options: Options
  value: Container
}) {
  const [open, setOpen] = useState(depth < options.initialDepth)
  const [shown, setShown] = useState(options.pageSize)
  const array = Array.isArray(value)
  const entries: [string, unknown][] = array
    ? value.map((v, i) => [String(i), v])
    : Object.entries(value)
  const [start, end] = array ? ['[', ']'] : ['{', '}']
  const hidden = entries.length - shown
  if (entries.length === 0)
    return (
      <Line value={value}>
        {name !== undefined && <Key name={name} />}
        <Punct>{start + end}</Punct>
        {!last && <Punct>,</Punct>}
      </Line>
    )
  return (
    <div>
      <div className="group/line hover:bg-muted/60 flex items-start gap-1 rounded-sm">
        <button
          aria-expanded={open}
          className="focus-visible:ring-ring flex min-w-0 flex-1 items-start rounded-sm text-left outline-none focus-visible:ring-2"
          onClick={() => setOpen(!open)}
          type="button"
        >
          <ChevronRight
            aria-hidden
            className={cn(
              'mt-0.75 size-3.5 shrink-0 text-muted-foreground transition-transform',
              open && 'rotate-90',
            )}
          />
          <span className="ml-0.5 min-w-0 wrap-anywhere">
            {name !== undefined && <Key name={name} />}
            <Punct>{start}</Punct>
            {!open && (
              <>
                <span className="text-muted-foreground px-1">
                  {preview(value)}
                </span>
                <Punct>{end}</Punct>
                {!last && <Punct>,</Punct>}
              </>
            )}
          </span>
        </button>
        <CopyButton value={value} />
      </div>
      {open && (
        <>
          <div className="border-border ml-1.75 border-l pl-2">
            {entries.slice(0, shown).map(([key, child], i) => (
              <Node
                depth={depth + 1}
                key={key}
                last={i === entries.length - 1}
                name={array ? undefined : key}
                options={options}
                value={child}
              />
            ))}
            {hidden > 0 && (
              <button
                className="text-muted-foreground hover:text-foreground focus-visible:ring-ring ml-4 rounded-sm underline-offset-2 outline-none hover:underline focus-visible:ring-2"
                onClick={() => setShown(shown + options.pageSize)}
                type="button"
              >
                {`Show ${Math.min(hidden, options.pageSize).toLocaleString('en-US')} more of ${hidden.toLocaleString('en-US')}`}
              </button>
            )}
          </div>
          <div className="pl-4">
            <Punct>{end}</Punct>
            {!last && <Punct>,</Punct>}
          </div>
        </>
      )}
    </div>
  )
}

function clipString(value: string, lines: number): null | string {
  const head = value.split('\n', lines + 1)
  if (head.length <= lines && value.length <= lines * CHARS_PER_LINE)
    return null
  return head
    .slice(0, lines)
    .join('\n')
    .slice(0, lines * CHARS_PER_LINE)
}

function CopyButton({ value }: { value: unknown }) {
  const { copied, copy } = useClipboard({ timeoutMs: 1500 })
  const label = copied ? 'Copied' : 'Copy'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          aria-label={label}
          className="size-5 shrink-0 opacity-0 group-hover/line:opacity-100 focus-visible:opacity-100 [&_svg]:size-3"
          onClick={() => void copy(copyText(value))}
          size="icon"
          variant="ghost"
        >
          {copied ? <Check /> : <Copy />}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  )
}

function copyText(value: unknown): string {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2) ?? String(value)
}

function isContainer(value: unknown): value is Container {
  return typeof value === 'object' && value !== null
}

function Key({ name }: { name: string }) {
  return (
    <>
      <span className={tone.key}>&quot;{name}&quot;</span>
      <Punct>: </Punct>
    </>
  )
}

function Line({ children, value }: { children: ReactNode; value: unknown }) {
  return (
    <div className="group/line hover:bg-muted/60 flex items-start gap-1 rounded-sm pl-4">
      <span className="min-w-0 flex-1 wrap-anywhere">{children}</span>
      <CopyButton value={value} />
    </div>
  )
}

function Node({
  depth,
  last,
  name,
  options,
  value,
}: {
  depth: number
  last: boolean
  name?: string
  options: Options
  value: unknown
}) {
  if (isContainer(value))
    return (
      <Branch
        depth={depth}
        last={last}
        name={name}
        options={options}
        value={value}
      />
    )
  const comma = !last && <Punct>,</Punct>
  return (
    <Line value={value}>
      {name !== undefined && <Key name={name} />}
      {typeof value === 'string' ? (
        <StringValue lines={options.stringLines} trail={comma} value={value} />
      ) : (
        <>
          <Primitive value={value} />
          {comma}
        </>
      )}
    </Line>
  )
}

function preview(value: Container): string {
  if (Array.isArray(value))
    return `${value.length} ${value.length === 1 ? 'item' : 'items'}`
  const keys = Object.keys(value).join(', ')
  return keys.length > PREVIEW_CHARS ? `${keys.slice(0, PREVIEW_CHARS)}…` : keys
}

function Primitive({ value }: { value: unknown }) {
  if (value === null || value === undefined)
    return <span className={tone.null}>{String(value)}</span>
  if (typeof value === 'boolean')
    return <span className={tone.boolean}>{String(value)}</span>
  return <span className={tone.number}>{String(value)}</span>
}

function Punct({ children }: { children: ReactNode }) {
  return <span className={tone.punct}>{children}</span>
}

function StringValue({
  lines,
  trail,
  value,
}: {
  lines: number
  trail: ReactNode
  value: string
}) {
  const [open, setOpen] = useState(false)
  const clipped = clipString(value, lines)
  const total = value.split('\n').length
  return (
    <>
      <span className={cn('whitespace-pre-wrap', tone.string)}>
        &quot;{clipped === null || open ? value : `${clipped}…`}&quot;
      </span>
      {trail}
      {clipped !== null && (
        <button
          aria-expanded={open}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring ml-2 rounded-sm underline-offset-2 outline-none hover:underline focus-visible:ring-2"
          onClick={() => setOpen(!open)}
          type="button"
        >
          {open
            ? 'Show less'
            : total > 1
              ? `Show all ${total.toLocaleString('en-US')} lines`
              : `Show all ${value.length.toLocaleString('en-US')} characters`}
        </button>
      )}
    </>
  )
}
