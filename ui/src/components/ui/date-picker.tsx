import { useState } from 'react'

import { format, isValid, parse, startOfToday } from 'date-fns'
import { CalendarIcon } from 'lucide-react'

import { Calendar } from '@/components/ui/calendar'
import { Input } from '@/components/ui/input'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from '@/components/ui/input-group'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { parseServerTs, toDateOnlyIso } from '@/lib/formatDate'
import { cn } from '@/lib/utils'

const SHOWN = 'MMM d, yyyy'

const TYPED = [
  'yyyy-MM-dd',
  SHOWN,
  'MMM d yyyy',
  'MMMM d, yyyy',
  'MMMM d yyyy',
  'M/d/yyyy',
  'd MMM yyyy',
  'd MMMM yyyy',
]

export interface DatePickerProps {
  'aria-label'?: string
  className?: string
  disabled?: boolean
  disablePast?: boolean
  id?: string
  modal?: boolean
  onChange: (value: string) => void
  placeholder?: string
  /** A calendar day as `YYYY-MM-DD`, or `''` for none. */
  value: string
}

export interface DateTimePickerProps {
  'aria-label': string
  className?: string
  modal?: boolean
  onChange: (value: string) => void
  /** `YYYY-MM-DDTHH:MM`, or `''` for none. */
  value: string
}

export function DatePicker({
  'aria-label': ariaLabel,
  className,
  disabled,
  disablePast = false,
  id,
  modal,
  onChange,
  placeholder = 'Pick a date',
  value,
}: DatePickerProps) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(() => shown(value))
  const [month, setMonth] = useState<Date | undefined>(() =>
    value ? parseServerTs(value) : undefined,
  )
  const [synced, setSynced] = useState(value)
  if (synced !== value) {
    setSynced(value)
    setText(shown(value))
    if (value) setMonth(parseServerTs(value))
  }

  const allowed = (date: Date) => !disablePast || date >= startOfToday()
  const typed = parseTypedDate(text)
  const invalid = text.trim() !== '' && !(typed && allowed(typed))

  const choose = (next: string) => {
    setText(shown(next))
    if (next !== value) onChange(next)
  }

  const commit = () => {
    if (text.trim() === '') choose('')
    else if (typed && allowed(typed)) choose(toDateOnlyIso(typed))
    else setText(shown(value))
  }

  return (
    <InputGroup className={className}>
      <InputGroupInput
        aria-invalid={invalid || undefined}
        aria-label={ariaLabel}
        disabled={disabled}
        id={id}
        onBlur={commit}
        onChange={(e) => {
          setText(e.target.value)
          const date = parseTypedDate(e.target.value)
          if (date) setMonth(date)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setOpen(true)
          } else if (e.key === 'Enter') {
            e.preventDefault()
            commit()
          }
        }}
        placeholder={placeholder}
        value={text}
      />
      <InputGroupAddon align="inline-end">
        <Popover modal={modal} onOpenChange={setOpen} open={open}>
          <PopoverTrigger asChild>
            <InputGroupButton aria-label="Choose date" disabled={disabled}>
              <CalendarIcon />
            </InputGroupButton>
          </PopoverTrigger>
          <PopoverContent
            align="end"
            alignOffset={-8}
            className="w-auto overflow-hidden p-0"
            sideOffset={10}
          >
            <Calendar
              disabled={disablePast ? { before: startOfToday() } : undefined}
              mode="single"
              month={month}
              onMonthChange={setMonth}
              onSelect={(date) => {
                if (date) choose(toDateOnlyIso(date))
                setOpen(false)
              }}
              selected={value ? parseServerTs(value) : undefined}
            />
          </PopoverContent>
        </Popover>
      </InputGroupAddon>
    </InputGroup>
  )
}

export function DateTimePicker({
  'aria-label': label,
  className,
  modal,
  onChange,
  value,
}: DateTimePickerProps) {
  const [date = '', time = ''] = value.split('T')
  return (
    <div className={cn('flex gap-2', className)}>
      <DatePicker
        aria-label={`${label} date`}
        className="flex-1"
        modal={modal}
        onChange={(d) => onChange(d ? `${d}T${time || '00:00'}` : '')}
        value={date}
      />
      <Input
        aria-label={`${label} time`}
        className="h-8 w-28 appearance-none py-0 [&::-webkit-calendar-picker-indicator]:hidden [&::-webkit-calendar-picker-indicator]:appearance-none"
        disabled={!date}
        onChange={(e) => onChange(`${date}T${e.target.value || '00:00'}`)}
        type="time"
        value={time.slice(0, 5)}
      />
    </div>
  )
}

function parseTypedDate(text: string): Date | null {
  const raw = text.trim().replace(/\s+/g, ' ')
  for (const pattern of TYPED) {
    const date = parse(raw, pattern, new Date())
    if (isValid(date) && date.getFullYear() >= 1000) return date
  }
  return null
}

function shown(value: string): string {
  return value ? format(parseServerTs(value), SHOWN) : ''
}
