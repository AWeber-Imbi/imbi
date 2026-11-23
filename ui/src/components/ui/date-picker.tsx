import { useState } from 'react'

import { format, isValid, parse, startOfToday } from 'date-fns'
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

const TIME_FORMATS = ['H:mm', 'h:mm a', 'h:mma', 'h a', 'ha']

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
        placeholder="mm/dd/yyyy"
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
  for (const pattern of TIME_FORMATS) {
    const date = parse(raw, pattern, new Date())
    if (isValid(date)) return format(date, 'HH:mm')
  }
  return null
}

function toDisplay(value: string): string {
  return value ? formatDayField(parseServerTs(value)) : ''
}
