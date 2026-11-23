import { useId, useState } from 'react'

import { subMonths } from 'date-fns'
import type { DateRange } from 'react-day-picker'

import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { TimeInput } from '@/components/ui/date-picker'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Separator } from '@/components/ui/separator'

export function LogsRangePicker({
  end,
  onApply,
  onCancel,
  start,
}: {
  end: Date
  onApply: (start: Date, end: Date) => void
  onCancel: () => void
  start: Date
}) {
  const id = useId()
  const [days, setDays] = useState<DateRange | undefined>({
    from: utcDay(start),
    to: utcDay(end),
  })
  const [startTime, setStartTime] = useState(utcTime(start))
  const [endTime, setEndTime] = useState(utcTime(end))
  const from = days?.from && atUtc(days.from, startTime)
  const to = days?.from && atUtc(days.to ?? days.from, endTime)
  const valid = !!from && !!to && from < to

  return (
    <div className="flex flex-col">
      <Calendar
        defaultMonth={subMonths(utcDay(end), 1)}
        mode="range"
        numberOfMonths={2}
        onSelect={setDays}
        selected={days}
      />
      <Separator />
      <FieldGroup className="grid grid-cols-2 gap-3 p-3">
        <TimeField
          id={`${id}-start`}
          label="Start (UTC)"
          onChange={setStartTime}
          value={startTime}
        />
        <TimeField
          id={`${id}-end`}
          label="End (UTC)"
          onChange={setEndTime}
          value={endTime}
        />
      </FieldGroup>
      <Separator />
      <div className="flex justify-end gap-2 p-3">
        <Button onClick={onCancel} size="sm" variant="ghost">
          Cancel
        </Button>
        <Button
          disabled={!valid}
          onClick={() => from && to && onApply(from, to)}
          size="sm"
        >
          Apply
        </Button>
      </div>
    </div>
  )
}

function atUtc(day: Date, time: string): Date | undefined {
  const [hours, minutes] = time.split(':').map(Number)
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return undefined
  return new Date(
    Date.UTC(day.getFullYear(), day.getMonth(), day.getDate(), hours, minutes),
  )
}

function TimeField({
  id,
  label,
  onChange,
  value,
}: {
  id: string
  label: string
  onChange: (value: string) => void
  value: string
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <TimeInput id={id} onChange={onChange} value={value} />
    </Field>
  )
}

function utcDay(date: Date): Date {
  return new Date(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())
}

function utcTime(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
}
