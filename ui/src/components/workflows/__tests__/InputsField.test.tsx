import { useState } from 'react'

import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'

import { InputsField } from '../InputsField'

function renderField(initial: Record<string, unknown> = {}) {
  const onChange = vi.fn()
  function Harness() {
    const [value, setValue] = useState(initial)
    return (
      <InputsField
        id="inputs"
        label="Inputs"
        onChange={(next) => {
          setValue(next)
          onChange(next)
        }}
        references={[]}
        value={value}
      />
    )
  }
  render(<Harness />)
  return onChange
}

describe('InputsField', () => {
  it('adds an input once it has a name', () => {
    const onChange = renderField()
    fireEvent.click(screen.getByRole('button', { name: 'Add input' }))
    expect(onChange).toHaveBeenLastCalledWith({})
    fireEvent.change(screen.getByLabelText('Input 1 name'), {
      target: { value: 'runs' },
    })
    fireEvent.change(screen.getByLabelText('Input 1 value'), {
      target: { value: '{{ trigger.runs }}' },
    })
    expect(onChange).toHaveBeenLastCalledWith({ runs: '{{ trigger.runs }}' })
  })

  it('keeps the type of a value it did not edit', () => {
    const onChange = renderField({ limit: 3, runs: '{{ trigger.runs }}' })
    fireEvent.change(screen.getByLabelText('Input 2 name'), {
      target: { value: 'items' },
    })
    expect(onChange).toHaveBeenLastCalledWith({
      items: '{{ trigger.runs }}',
      limit: 3,
    })
  })

  it('flags a bad or repeated name', () => {
    renderField({ limit: 3 })
    fireEvent.click(screen.getByRole('button', { name: 'Add input' }))
    fireEvent.change(screen.getByLabelText('Input 2 name'), {
      target: { value: 'limit' },
    })
    expect(screen.getByText('Another input has this name.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Input 2 name'), {
      target: { value: 'Bad-Name' },
    })
    expect(
      screen.getByText(
        'Use lowercase letters, digits, and _, starting with a letter.',
      ),
    ).toBeInTheDocument()
  })

  it('removes an input', () => {
    const onChange = renderField({ a: 1, b: 2 })
    fireEvent.click(screen.getByRole('button', { name: 'Remove input 1' }))
    expect(onChange).toHaveBeenLastCalledWith({ b: 2 })
  })
})
