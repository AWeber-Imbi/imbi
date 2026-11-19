import {
  type ComponentType,
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'

import { Braces, Check, Copy, FileText } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Separator } from '@/components/ui/separator'
import { Toggle } from '@/components/ui/toggle'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { IconTooltip } from '@/components/ui/tooltip'
import type { Ticket } from '@/types'

import { conversationMarkdown } from './conversationMarkdown'
import { turns } from './conversationTurns'
import { isFailed } from './taskEvents'
import { timeline } from './taskTimeline'

export interface ToolbarOption<T extends string> {
  hint?: string
  icon: Icon
  label: string
  value: T
}

type Icon = ComponentType<{ className?: string }>

export const TOOLBAR_ITEM =
  'text-secondary hover:text-primary aria-disabled:cursor-not-allowed aria-disabled:opacity-50 aria-disabled:hover:bg-transparent aria-disabled:hover:text-secondary aria-checked:bg-amber-bg aria-checked:text-amber-text aria-pressed:bg-amber-bg aria-pressed:text-amber-text'

/** Copy the task as a Markdown transcript, or its record and events as JSON. */
export function TaskCopyMenu({
  events,
  task,
}: {
  events: Parameters<typeof timeline>[0]
  task: Ticket
}) {
  const [copied, setCopied] = useState<null | string>(null)
  const [error, setError] = useState<null | string>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  const copy = useCallback(async (format: string, text: () => string) => {
    try {
      await navigator.clipboard.writeText(text())
      setError(null)
      setCopied(format)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(null), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not copy.')
    }
  }, [])
  const formats: { icon: Icon; label: string; text: () => string }[] = [
    {
      icon: FileText,
      label: 'Markdown',
      text: () =>
        conversationMarkdown(
          task,
          turns(timeline(events), {
            failed: isFailed(task),
            live: task.status === 'running',
          }),
        ),
    },
    {
      icon: Braces,
      label: 'JSON',
      text: () => JSON.stringify({ events, task }, null, 2),
    },
  ]
  return (
    <>
      {error && (
        <span className="text-danger text-xs" role="alert">
          {error}
        </span>
      )}
      <DropdownMenu>
        <IconTooltip label={copied ? `Copied ${copied}` : 'Copy'}>
          <DropdownMenuTrigger asChild>
            <Button
              aria-label={copied ? `Copied ${copied}` : 'Copy'}
              className="size-8 p-0"
              size="sm"
              type="button"
              variant="outline"
            >
              {copied ? (
                <Check className="size-4" />
              ) : (
                <Copy className="size-4" />
              )}
            </Button>
          </DropdownMenuTrigger>
        </IconTooltip>
        <DropdownMenuContent align="end" className="min-w-44 p-1">
          <DropdownMenuGroup>
            {formats.map(({ icon: FormatIcon, label, text }) => (
              <DropdownMenuItem
                className="gap-2.5 px-3 py-2"
                key={label}
                onSelect={() => void copy(label, text)}
              >
                <FormatIcon className="size-4" />
                Copy as {label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  )
}

/** Controls that lead every toolbar of a view, such as the view switch. */
export const ToolbarLead = createContext<ReactNode>(null)

/** The row above every task view: view options first, search and copy at the end. */
export function TaskToolbar({
  children,
  label,
}: {
  children: ReactNode
  label: string
}) {
  const lead = useContext(ToolbarLead)
  return (
    <div
      aria-label={label}
      className="border-tertiary bg-tertiary flex min-h-12 shrink-0 flex-wrap items-center gap-2 border-b px-6 py-2"
      role="toolbar"
    >
      {lead && (
        <>
          {lead}
          <Separator className="mx-1 h-5" orientation="vertical" />
        </>
      )}
      {children}
    </div>
  )
}

export function ToolbarChoice<T extends string>({
  label,
  onChange,
  options,
  value,
}: {
  label: string
  onChange: (value: T) => void
  options: ToolbarOption<T>[]
  value: T
}) {
  return (
    <ToggleGroup
      aria-label={label}
      onValueChange={(v) => {
        const option = options.find((o) => o.value === v)
        if (option) onChange(option.value)
      }}
      spacing={0}
      type="single"
      value={value}
      variant="outline"
    >
      {options.map(({ hint, icon: Icon, label: name, value: v }) => (
        <IconTooltip key={v} label={hint ?? name}>
          <ToggleGroupItem aria-label={name} className={TOOLBAR_ITEM} value={v}>
            <Icon />
          </ToggleGroupItem>
        </IconTooltip>
      ))}
    </ToggleGroup>
  )
}

export function ToolbarToggle({
  disabled,
  hint,
  icon: Icon,
  label,
  onPressedChange,
  pressed,
}: {
  /** Why the toggle is off; it stays hoverable so the tooltip can say so. */
  disabled?: string
  hint?: string
  icon: Icon
  label: string
  onPressedChange: (pressed: boolean) => void
  pressed: boolean
}) {
  return (
    <IconTooltip
      label={
        disabled ? (
          <span className="flex flex-col gap-0.5">
            <span>{hint ?? label}</span>
            <span className="text-muted-foreground text-xs">{disabled}</span>
          </span>
        ) : (
          (hint ?? label)
        )
      }
    >
      <Toggle
        aria-disabled={disabled ? true : undefined}
        aria-label={label}
        className={TOOLBAR_ITEM}
        onPressedChange={(next) => {
          if (!disabled) onPressedChange(next)
        }}
        pressed={pressed}
        variant="outline"
      >
        <Icon />
      </Toggle>
    </IconTooltip>
  )
}
