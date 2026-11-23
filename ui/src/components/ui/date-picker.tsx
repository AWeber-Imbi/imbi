import { useEffect, useRef, useState } from 'react'

import { isValid, parse, startOfToday } from 'date-fns'
import { CalendarIcon, Clock2Icon } from 'lucide-react'

import { Calendar } from '@/components/ui/calendar'
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
import { formatDayField, parseServerTs, toDateOnlyIso } from '@/lib/formatDate'
import { cn } from '@/lib/utils'

const ACCEPTED_FORMATS = [
  'M/d/yyyy',
  'yyyy-MM-dd',
  'MMM d, yyyy',
  'MMM d yyyy',
  'MMMM d, yyyy',
  'MMMM d yyyy',
  'd MMM yyyy',
  'd MMMM yyyy',
]

export interface DatePickerProps {
  'aria-label'?: string
  className?: string
  disabled?: boolean
  disablePast?: boolean
  id?: string
  keepInvalid?: boolean
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

export interface TimeInputProps {
  'aria-label'?: string
  className?: string
  disabled?: boolean
  id?: string
  onChange: (value: string) => void
  value: string
}

export function DatePicker({
  'aria-label': ariaLabel,
  className,
  disabled,
  disablePast = false,
  id,
  keepInvalid = false,
  modal,
  onChange,
  required = false,
  value,
}: DatePickerProps) {
  const input = useRef<HTMLInputElement>(null)
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
  const problem = !invalid
    ? ''
    : typed
      ? 'Pick today or a later date'
      : 'Enter a date as mm/dd/yyyy'
  useEffect(() => {
    input.current?.setCustomValidity(problem)
  }, [problem])

  const choose = (next: string) => {
    setText(toDisplay(next))
    if (next === lastSent) return
    setLastSent(next)
    onChange(next)
  }

  const commit = () => {
    if (empty && !required) choose('')
    else if (typed && allowed(typed)) choose(toDateOnlyIso(typed))
    else if (!keepInvalid) {
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
        placeholder="mm/dd/yyyy"
        ref={input}
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
      <TimeInput
        aria-label={`${label} time`}
        className="h-10 w-36"
        disabled={!date}
        onChange={(t) => onChange(`${date}T${t || '00:00'}`)}
        value={time.slice(0, 5)}
      />
    </div>
  )
}

export function TimeInput({
  'aria-label': ariaLabel,
  className,
  disabled,
  id,
  onChange,
  value,
}: TimeInputProps) {
  const [text, setText] = useState(value)
  const [prevValue, setPrevValue] = useState(value)
  if (prevValue !== value) {
    setPrevValue(value)
    setText(value)
  }

  const typed = parseTypedTime(text)
  const invalid = text.trim() !== '' && !typed

  const commit = () => {
    setText(typed ?? value)
    if (typed && typed !== value) onChange(typed)
  }

  return (
    <InputGroup className={className}>
      <InputGroupInput
        aria-invalid={invalid || undefined}
        aria-label={ariaLabel}
        disabled={disabled}
        id={id}
        inputMode="numeric"
        onBlur={commit}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            commit()
          }
        }}
        placeholder="hh:mm"
        value={text}
      />
      <InputGroupAddon align="inline-end">
        <span className="text-secondary flex size-6 items-center justify-center">
          <Clock2Icon className="size-3.5" />
        </span>
      </InputGroupAddon>
    </InputGroup>
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

function parseTypedTime(text: string): null | string {
  const raw = text.trim().replace(/\s+/g, ' ').toUpperCase()
  const clock = /^(\d{1,2}):(\d{2})$/.exec(raw)
  const meridiem = /^(\d{1,2})(?::(\d{2}))? ?([AP])M$/.exec(raw)
  let hours: number
  let minutes: number
  if (clock) {
    hours = Number(clock[1])
    minutes = Number(clock[2])
    if (hours > 23) return null
  } else if (meridiem) {
    const hour = Number(meridiem[1])
    if (hour < 1 || hour > 12) return null
    hours = (hour % 12) + (meridiem[3] === 'P' ? 12 : 0)
    minutes = Number(meridiem[2] ?? 0)
  } else return null
  if (minutes > 59) return null
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(hours)}:${pad(minutes)}`
}

function toDisplay(value: string): string {
  return value ? formatDayField(parseServerTs(value)) : ''
}
