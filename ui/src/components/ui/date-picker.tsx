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

const DISPLAY_FORMAT = 'MMM d, yyyy'

const ACCEPTED_FORMATS = [
  'yyyy-MM-dd',
  DISPLAY_FORMAT,
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
  required?: boolean
  value: string
}

export interface DateTimePickerProps {
  'aria-label': string
  className?: string
  onChange: (value: string) => void
  required?: boolean
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
  required = false,
  value,
}: DatePickerProps) {
  const selected = value ? parseServerTs(value) : undefined
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(() => toDisplay(value))
  const [month, setMonth] = useState(selected)
  const [prevValue, setPrevValue] = useState(value)
  const [lastSent, setLastSent] = useState(value)
  if (prevValue !== value) {
    setPrevValue(value)
    setLastSent(value)
    setText(toDisplay(value))
    if (selected) setMonth(selected)
  }

  const earliest = disablePast ? startOfToday() : undefined
  const allowed = (date: Date) => !disablePast || date >= startOfToday()
  const typed = parseTypedDate(text)
  const empty = text.trim() === ''
  const invalid = !empty && !(typed && allowed(typed))

  const choose = (next: string) => {
    setText(toDisplay(next))
    if (next === lastSent) return
    setLastSent(next)
    onChange(next)
  }

  const commit = () => {
    if (empty && !required) choose('')
    else if (typed && allowed(typed)) choose(toDateOnlyIso(typed))
    else {
      setText(toDisplay(value))
      setMonth(selected)
    }
  }

  const openCalendar = (next: boolean) => {
    if (next) setLastSent(value)
    setOpen(next)
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
          setLastSent(value)
          const date = parseTypedDate(e.target.value)
          if (date) setMonth(date)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            openCalendar(true)
          } else if (e.key === 'Enter') {
            e.preventDefault()
            commit()
          }
        }}
        placeholder="Pick a date"
        required={required}
        value={text}
      />
      <InputGroupAddon align="inline-end">
        <Popover modal={modal} onOpenChange={openCalendar} open={open}>
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
              disabled={earliest && { before: earliest }}
              mode="single"
              month={month}
              onMonthChange={setMonth}
              onSelect={(date) => {
                if (date && allowed(date)) choose(toDateOnlyIso(date))
                setOpen(false)
              }}
              selected={selected}
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
  onChange,
  required,
  value,
}: DateTimePickerProps) {
  const [date = '', time = ''] = value.split('T')
  return (
    <div className={cn('flex gap-2', className)}>
      <DatePicker
        aria-label={`${label} date`}
        className="h-10 flex-1"
        onChange={(d) => onChange(d ? `${d}T${time || '00:00'}` : '')}
        required={required}
        value={date}
      />
      <Input
        aria-label={`${label} time`}
        className="w-32 appearance-none [&::-webkit-calendar-picker-indicator]:hidden [&::-webkit-calendar-picker-indicator]:appearance-none"
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
  for (const pattern of ACCEPTED_FORMATS) {
    const date = parse(raw, pattern, new Date())
    if (isValid(date) && date.getFullYear() >= 1000) return date
  }
  return null
}

function toDisplay(value: string): string {
  return value ? format(parseServerTs(value), DISPLAY_FORMAT) : ''
}
