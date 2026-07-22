import { useEffect, useRef, useState } from 'react'

import { X } from 'lucide-react'
import { toast } from 'sonner'

import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { cn } from '@/lib/utils'

import { InlineDisplay } from './InlineDisplay'

export interface InlineArrayProps {
  itemType?: 'integer' | 'number' | 'string'
  onCommit: (next: unknown[]) => Promise<void> | void
  pending?: boolean
  placeholder?: string
  readOnly?: boolean
  values: unknown[]
}

const sameList = (a: unknown[], b: unknown[]) =>
  a.length === b.length && a.every((v, i) => v === b[i])

const INTEGER_RE = /^-?\d+$/
const NUMBER_RE = /^-?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/

const coerce = (
  raw: string,
  type: 'integer' | 'number' | 'string',
): null | number | string => {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  if (type === 'integer') {
    if (!INTEGER_RE.test(trimmed)) return null
    const n = Number(trimmed)
    return Number.isSafeInteger(n) ? n : null
  }
  if (type === 'number') {
    if (!NUMBER_RE.test(trimmed)) return null
    const n = Number(trimmed)
    return Number.isFinite(n) ? n : null
  }
  return trimmed
}

export function InlineArray({
  itemType = 'string',
  onCommit,
  pending = false,
  placeholder = 'Add…',
  readOnly = false,
  values,
}: InlineArrayProps) {
  const interactive = !pending && !readOnly
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<unknown[]>(values)
  const [entry, setEntry] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setDraft(values)
      setEntry('')
      // Defer focus until popover content is mounted.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open, values])

  const addEntry = () => {
    const v = coerce(entry, itemType)
    if (v === null) return
    setDraft((cur) => [...cur, v])
    setEntry('')
  }

  const removeAt = (index: number) => {
    setDraft((cur) => cur.filter((_, i) => i !== index))
  }

  const close = async () => {
    setOpen(false)
    // Flush any unsubmitted entry.
    const pendingValue = coerce(entry, itemType)
    const next =
      pendingValue !== null ? [...draft, pendingValue] : draft.slice()
    if (sameList(next, values)) return
    try {
      await onCommit(next)
    } catch (e) {
      setDraft(values)
      toast.error(e instanceof Error ? e.message : 'Save failed')
    }
  }

  const display = values.map((v) => String(v)).join(', ')

  return (
    <Popover
      onOpenChange={(next) => {
        if (!interactive) return
        if (next) setOpen(true)
        else void close()
      }}
      open={open}
    >
      <PopoverTrigger asChild>
        <span>
          <InlineDisplay
            hasValue={values.length > 0}
            onClick={() => {
              if (interactive) setOpen(true)
            }}
            pending={pending}
            placeholder={placeholder}
            readOnly={readOnly}
          >
            <span className="text-primary text-sm">{display}</span>
          </InlineDisplay>
        </span>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-3">
        <div className="space-y-2">
          {draft.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              {draft.map((v, i) => (
                <li
                  className={cn(
                    'inline-flex items-center gap-1 rounded-sm border',
                    'bg-secondary/40 py-0.5 pr-1 pl-2 text-xs',
                  )}
                  key={`${i}-${String(v)}`}
                >
                  <span className="text-primary">{String(v)}</span>
                  <button
                    aria-label={`Remove ${String(v)}`}
                    className="text-tertiary hover:bg-secondary hover:text-primary rounded p-0.5"
                    disabled={!interactive}
                    onClick={() => removeAt(i)}
                    type="button"
                  >
                    <X className="size-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Input
            className="h-7 py-1 text-sm"
            disabled={!interactive}
            inputMode={itemType === 'string' ? 'text' : 'numeric'}
            onChange={(e) => setEntry(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addEntry()
              }
            }}
            placeholder="Add item and press Enter"
            ref={inputRef}
            value={entry}
          />
        </div>
      </PopoverContent>
    </Popover>
  )
}
