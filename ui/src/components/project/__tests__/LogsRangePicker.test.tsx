import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { LogsRangePicker } from '../LogsRangePicker'

describe('LogsRangePicker', () => {
  it('starts from the current range and applies it in UTC', () => {
    const onApply = vi.fn()
    render(
      <LogsRangePicker
        end={new Date('2099-03-05T17:27:00Z')}
        onApply={onApply}
        onCancel={vi.fn()}
        start={new Date('2099-03-04T16:27:00Z')}
      />,
    )
    expect(screen.getByText('March 2099')).toBeVisible()
    expect(screen.getByLabelText('End (UTC)')).toHaveValue('17:27')
    const startTime = screen.getByLabelText('Start (UTC)')
    fireEvent.change(startTime, { target: { value: '8:00' } })
    fireEvent.blur(startTime)
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply).toHaveBeenCalledExactlyOnceWith(
      new Date('2099-03-04T08:00:00Z'),
      new Date('2099-03-05T17:27:00Z'),
    )
  })

  it('does not apply a range that ends before it starts', () => {
    render(
      <LogsRangePicker
        end={new Date('2099-03-04T17:00:00Z')}
        onApply={vi.fn()}
        onCancel={vi.fn()}
        start={new Date('2099-03-04T16:00:00Z')}
      />,
    )
    const endTime = screen.getByLabelText('End (UTC)')
    fireEvent.change(endTime, { target: { value: '15:00' } })
    fireEvent.blur(endTime)
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
  })
})
