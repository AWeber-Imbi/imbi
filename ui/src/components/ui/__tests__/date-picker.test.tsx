import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DatePicker, DateTimePicker } from '../date-picker'

function typeAndLeave(label: string, text: string) {
  const input = screen.getByLabelText(label)
  fireEvent.change(input, { target: { value: text } })
  fireEvent.blur(input)
  return input
}

describe('DatePicker', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it.each([
    ['2099-12-01', '2099-12-01'],
    ['12/1/2099', '2099-12-01'],
    ['Dec 1, 2099', '2099-12-01'],
    ['december 1 2099', '2099-12-01'],
    ['1 Dec 2099', '2099-12-01'],
  ])('reads a typed %s as the calendar day', (typed, day) => {
    const onChange = vi.fn()
    render(<DatePicker aria-label="Due" onChange={onChange} value="" />)
    expect(typeAndLeave('Due', typed)).toHaveValue('Dec 1, 2099')
    expect(onChange).toHaveBeenCalledExactlyOnceWith(day)
  })

  it.each([
    ['garbage', false],
    ['2/30/2099', false],
    ['1/2/2', false],
    ['1/1/2020', true],
  ])('puts back the previous day for %s', async (typed, disablePast) => {
    const onChange = vi.fn()
    render(
      <DatePicker
        aria-label="Due"
        disablePast={disablePast}
        onChange={onChange}
        value="2099-03-04"
      />,
    )
    const input = screen.getByLabelText('Due')
    fireEvent.change(input, { target: { value: typed } })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    fireEvent.blur(input)
    expect(input).toHaveValue('Mar 4, 2099')
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Choose date' }))
    expect(await screen.findByText('March 2099')).toBeVisible()
  })

  it('clears the day when the text is emptied', () => {
    const onChange = vi.fn()
    render(
      <DatePicker aria-label="Due" onChange={onChange} value="2099-03-04" />,
    )
    typeAndLeave('Due', '')
    expect(onChange).toHaveBeenCalledExactlyOnceWith('')
  })

  it('puts back the day when a required field is emptied', () => {
    const onChange = vi.fn()
    render(
      <DatePicker
        aria-label="Since"
        onChange={onChange}
        required
        value="2099-03-04"
      />,
    )
    expect(typeAndLeave('Since', '')).toHaveValue('Mar 4, 2099')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('commits on Enter, once', () => {
    const onChange = vi.fn()
    render(<DatePicker aria-label="Due" onChange={onChange} value="" />)
    const input = screen.getByLabelText('Due')
    fireEvent.change(input, { target: { value: '2099-12-01' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.blur(input)
    expect(onChange).toHaveBeenCalledExactlyOnceWith('2099-12-01')
  })

  it('sends the same day again after the parent kept the old one', () => {
    const onChange = vi.fn()
    render(
      <DatePicker aria-label="Due" onChange={onChange} value="2099-03-04" />,
    )
    typeAndLeave('Due', '2099-03-05')
    typeAndLeave('Due', '2099-03-05')
    expect(onChange).toHaveBeenCalledTimes(2)
  })

  it('rejects a day that became the past while typing', () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2099, 2, 15, 23, 59))
    const onChange = vi.fn()
    render(
      <DatePicker aria-label="Due" disablePast onChange={onChange} value="" />,
    )
    const input = screen.getByLabelText('Due')
    fireEvent.change(input, { target: { value: '2099-03-15' } })
    vi.setSystemTime(new Date(2099, 2, 16, 0, 1))
    fireEvent.blur(input)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('keeps focus on the next-month button as the month changes', async () => {
    render(
      <DatePicker aria-label="Due" onChange={vi.fn()} value="2099-03-04" />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Choose date' }))
    const next = await screen.findByRole('button', { name: /next month/i })
    next.focus()
    fireEvent.click(next)
    expect(await screen.findByText('April 2099')).toBeVisible()
    expect(next).toHaveFocus()
  })

  it('does not send anything when left unchanged', () => {
    const onChange = vi.fn()
    render(
      <DatePicker aria-label="Due" onChange={onChange} value="2099-03-04" />,
    )
    fireEvent.blur(screen.getByLabelText('Due'))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('shows a new value from the parent', () => {
    const { rerender } = render(
      <DatePicker aria-label="Due" onChange={vi.fn()} value="2099-03-04" />,
    )
    rerender(
      <DatePicker aria-label="Due" onChange={vi.fn()} value="2099-04-05" />,
    )
    expect(screen.getByLabelText('Due')).toHaveValue('Apr 5, 2099')
  })

  it('picks a day from the calendar', async () => {
    const onChange = vi.fn()
    render(
      <DatePicker
        aria-label="Due"
        disablePast
        onChange={onChange}
        value="2099-03-04"
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Choose date' }))
    expect(
      await screen.findByRole('button', { name: /March 4th/ }),
    ).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /March 20th/ }))
    expect(onChange).toHaveBeenCalledExactlyOnceWith('2099-03-20')
  })

  it('disables the days before today', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2099, 2, 15, 12))
    render(
      <DatePicker aria-label="Due" disablePast onChange={vi.fn()} value="" />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Choose date' }))
    expect(
      await screen.findByRole('button', { name: /March 14th/ }),
    ).toBeDisabled()
    expect(screen.getByRole('button', { name: /March 15th/ })).toBeEnabled()
  })
})

describe('DateTimePicker', () => {
  it('keeps the time when the day changes, and the day when the time does', () => {
    const onChange = vi.fn()
    render(
      <DateTimePicker
        aria-label="Run once at"
        onChange={onChange}
        value="2099-03-04T09:30"
      />,
    )
    typeAndLeave('Run once at date', '2099-03-05')
    expect(onChange).toHaveBeenLastCalledWith('2099-03-05T09:30')
    fireEvent.change(screen.getByLabelText('Run once at time'), {
      target: { value: '17:05' },
    })
    expect(onChange).toHaveBeenLastCalledWith('2099-03-04T17:05')
  })

  it('needs a day before it takes a time, then starts at midnight', () => {
    const onChange = vi.fn()
    render(<DateTimePicker aria-label="Start" onChange={onChange} value="" />)
    expect(screen.getByLabelText('Start time')).toBeDisabled()
    typeAndLeave('Start date', '2099-03-05')
    expect(onChange).toHaveBeenCalledExactlyOnceWith('2099-03-05T00:00')
  })
})
