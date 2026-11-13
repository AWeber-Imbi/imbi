import { useState } from 'react'

import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'

import type { Condition } from '../conditions'
import { ConditionsField } from '../ConditionsField'
import type { ReferenceGroup } from '../references'

const OPERATORS = [
  { label: 'equals', value: 'equals' },
  { label: 'is greater than', value: 'greater_than' },
  { label: 'is empty', value: 'is_empty' },
]

const GROUPS: ReferenceGroup[] = [
  {
    key: 'triage',
    mayNotRun: false,
    references: [{ path: 'triage.result.risk', type: 'string' }],
    title: 'Triage',
  },
]

function renderField(initial: Condition[] = []) {
  const onChange = vi.fn()
  function Harness() {
    const [value, setValue] = useState(initial)
    return (
      <ConditionsField
        id="conditions"
        label="Conditions"
        onChange={(next) => {
          setValue(next)
          onChange(next)
        }}
        operators={OPERATORS}
        references={GROUPS}
        value={value}
      />
    )
  }
  render(<Harness />)
  return onChange
}

describe('ConditionsField', () => {
  it('adds a row and edits both sides', () => {
    const onChange = renderField()
    fireEvent.click(screen.getByRole('button', { name: 'Add condition' }))
    expect(onChange).toHaveBeenLastCalledWith([
      { a: '', b: '', operator: 'equals' },
    ])
    fireEvent.change(screen.getByLabelText('Condition 1 value'), {
      target: { value: '{{ trigger.env }}' },
    })
    fireEvent.change(screen.getByLabelText('Condition 1 compared value'), {
      target: { value: 'production' },
    })
    expect(onChange).toHaveBeenLastCalledWith([
      { a: '{{ trigger.env }}', b: 'production', operator: 'equals' },
    ])
  })

  it('keeps the type of a value that is not text', () => {
    const onChange = renderField([{ a: ['abc'], b: 'a', operator: 'contains' }])
    fireEvent.change(screen.getByLabelText('Condition 1 value'), {
      target: { value: '["abc", "d"]' },
    })
    fireEvent.change(screen.getByLabelText('Condition 1 compared value'), {
      target: { value: '5' },
    })
    expect(onChange).toHaveBeenLastCalledWith([
      { a: ['abc', 'd'], b: '5', operator: 'contains' },
    ])
  })

  it('hides b for an empty check', async () => {
    const onChange = renderField([{ a: 'x', b: 'y', operator: 'equals' }])
    fireEvent.click(screen.getByLabelText('Condition 1 operator'))
    fireEvent.click(await screen.findByRole('option', { name: 'is empty' }))
    expect(onChange).toHaveBeenLastCalledWith([
      { a: 'x', operator: 'is_empty' },
    ])
    expect(
      screen.queryByLabelText('Condition 1 compared value'),
    ).not.toBeInTheDocument()
  })

  it('removes a row', () => {
    const onChange = renderField([
      { a: 'x', b: 'y', operator: 'equals' },
      { a: '', operator: 'is_empty' },
    ])
    fireEvent.click(screen.getByRole('button', { name: 'Remove condition 1' }))
    expect(onChange).toHaveBeenLastCalledWith([{ a: '', operator: 'is_empty' }])
  })

  it('outlines a row whose reference does not fit the operator', () => {
    renderField([
      { a: '{{ triage.result.risk }}', b: '3', operator: 'greater_than' },
      { a: '{{ triage.result.risk }}', b: 'high', operator: 'equals' },
    ])
    const warning = screen.getByText(
      '{{ triage.result.risk }} is string, but "is greater than" needs a number.',
    )
    expect(warning.parentElement).toHaveClass('border-danger')
    expect(screen.getAllByText(/needs/)).toHaveLength(1)
  })

  it('stops at ten rows', () => {
    renderField(
      Array.from({ length: 10 }, () => ({ a: '', operator: 'is_empty' })),
    )
    expect(
      screen.queryByRole('button', { name: 'Add condition' }),
    ).not.toBeInTheDocument()
  })
})
