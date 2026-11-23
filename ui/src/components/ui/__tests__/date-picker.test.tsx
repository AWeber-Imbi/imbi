import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DatePicker, DateTimePicker } from '../date-picker'

function typeAndLeave(text: string) {
  const input = screen.getByLabelText('Due')
  fireEvent.change(input, { target: { value: text } })
  fireEvent.blur(input)
  return input
}

describe('DatePicker', () => {
  it.each([
    ['2099-12-01', '2099-12-01'],
    ['12/1/2099', '2099-12-01'],
    ['Dec 1, 2099', '2099-12-01'],
    ['december 1 2099', '2099-12-01'],
    ['1 Dec 2099', '2099-12-01'],
  ])('reads a typed %s as the calendar day', (typed, day) => {
    const onChange = vi.fn()
    render(<DatePicker aria-label="Due" onChange={onChange} value="" />)
    expect(typeAndLeave(typed)).toHaveValue('Dec 1, 2099')
    expect(onChange).toHaveBeenCalledExactlyOnceWith(day)
  })

  it.each(['garbage', '2/30/2099', '1/2/2', '1/1/2020'])(
    'puts back the previous day for %s',
    (typed) => {
      const onChange = vi.fn()
      render(
        <DatePicker
          aria-label="Due"
          disablePast
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
    },
  )

  it('clears the day when the text is emptied', () => {
    const onChange = vi.fn()
    render(
      <DatePicker aria-label="Due" onChange={onChange} value="2099-03-04" />,
    )
    typeAndLeave('')
    expect(onChange).toHaveBeenCalledExactlyOnceWith('')
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
    render(
      <DatePicker aria-label="Due" disablePast onChange={vi.fn()} value="" />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Choose date' }))
    const today = new Date()
    const days = await screen.findAllByRole('button', {
      name: new RegExp(
        today.toLocaleDateString('en-US', { month: 'long' }) + ' \\d',
      ),
    })
    const disabled = days.filter((d) => (d as HTMLButtonElement).disabled)
    expect(disabled).toHaveLength(today.getDate() - 1)
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
    const day = screen.getByLabelText('Run once at date')
    fireEvent.change(day, { target: { value: '2099-03-05' } })
    fireEvent.blur(day)
    expect(onChange).toHaveBeenLastCalledWith('2099-03-05T09:30')
    fireEvent.change(screen.getByLabelText('Run once at time'), {
      target: { value: '17:05' },
    })
    expect(onChange).toHaveBeenLastCalledWith('2099-03-04T17:05')
  })

  it('needs a day before it takes a time', () => {
    render(<DateTimePicker aria-label="Start" onChange={vi.fn()} value="" />)
    expect(screen.getByLabelText('Start time')).toBeDisabled()
  })
})
