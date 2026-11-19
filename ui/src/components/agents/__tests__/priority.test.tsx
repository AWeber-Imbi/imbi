import { fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'

import { PriorityBadge, PriorityPicker } from '../priority'
import { systemText } from '../taskText'
import { event } from './taskFixtures'

describe('PriorityBadge', () => {
  it('shows every priority but the default', () => {
    const { container, rerender } = render(<PriorityBadge priority="normal" />)
    expect(container).toBeEmptyDOMElement()
    rerender(<PriorityBadge priority="urgent" />)
    expect(screen.getByText('Urgent')).toBeInTheDocument()
  })
})

describe('PriorityPicker', () => {
  it('checks the value and reports a choice', () => {
    const onChange = vi.fn()
    render(<PriorityPicker onChange={onChange} value="normal" />)
    expect(screen.getByRole('radio', { name: 'Normal' })).toBeChecked()
    fireEvent.click(screen.getByRole('radio', { name: 'High' }))
    expect(onChange).toHaveBeenCalledWith('high')
  })
})

it('describes a priority change', () => {
  expect(
    systemText(event(2, 'priority.changed', { from: 'normal', to: 'high' })),
  ).toBe('Priority normal → high')
})
