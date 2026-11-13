import { useState } from 'react'

import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'

import type { OutputField } from '../outputFields'
import { OutputFieldsField } from '../OutputFieldsField'

function renderField(initial: OutputField[] = []) {
  const onChange = vi.fn()
  function Harness() {
    const [value, setValue] = useState(initial)
    return (
      <OutputFieldsField
        id="fields"
        label="Output fields"
        onChange={(next) => {
          setValue(next)
          onChange(next)
        }}
        value={value}
      />
    )
  }
  render(<Harness />)
  return onChange
}

describe('OutputFieldsField', () => {
  it('names the group of fields', () => {
    renderField()
    expect(
      screen.getByRole('group', { name: 'Output fields' }),
    ).toBeInTheDocument()
  })

  it('adds a required string field', () => {
    const onChange = renderField()
    fireEvent.click(screen.getByRole('button', { name: 'Add field' }))
    expect(onChange).toHaveBeenLastCalledWith([
      { name: 'field_1', required: true, type: 'string' },
    ])
    expect(screen.getByLabelText('Field 1 name')).toHaveValue('field_1')
    expect(screen.getByLabelText('Field 1 required')).toBeChecked()
  })

  it('shows sub-fields once a field becomes an object', async () => {
    const onChange = renderField([{ name: 'owner', type: 'string' }])
    fireEvent.click(screen.getByLabelText('Field 1 type'))
    fireEvent.click(await screen.findByRole('option', { name: 'object' }))
    expect(onChange).toHaveBeenLastCalledWith([
      {
        fields: [{ name: 'field_1', required: true, type: 'string' }],
        name: 'owner',
        type: 'object',
      },
    ])
    expect(screen.getByLabelText('Field 1.1 name')).toHaveValue('field_1')
    expect(
      screen.getByRole('button', { name: 'Add sub-field' }),
    ).toBeInTheDocument()
  })

  it('limits a string to a list of values or a format', async () => {
    const onChange = renderField([{ name: 'risk', type: 'string' }])
    fireEvent.click(screen.getByLabelText('Field 1 values'))
    fireEvent.click(
      await screen.findByRole('option', { name: 'One of a list of values' }),
    )
    fireEvent.change(screen.getByLabelText('Field 1 allowed value 1'), {
      target: { value: 'low' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add value' }))
    fireEvent.change(screen.getByLabelText('Field 1 allowed value 2'), {
      target: { value: 'high' },
    })
    expect(onChange).toHaveBeenLastCalledWith([
      { enum: ['low', 'high'], name: 'risk', type: 'string' },
    ])
    fireEvent.click(screen.getByLabelText('Field 1 values'))
    fireEvent.click(await screen.findByRole('option', { name: 'A date' }))
    expect(onChange).toHaveBeenLastCalledWith([
      { format: 'date', name: 'risk', type: 'string' },
    ])
    expect(
      screen.queryByLabelText('Field 1 allowed value 1'),
    ).not.toBeInTheDocument()
  })

  it('goes back to any text when the last value is removed', () => {
    const onChange = renderField([
      { enum: ['low'], name: 'risk', type: 'string' },
    ])
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove field 1 allowed value 1' }),
    )
    expect(onChange).toHaveBeenLastCalledWith([
      { name: 'risk', type: 'string' },
    ])
    expect(screen.getByLabelText('Field 1 values')).toHaveTextContent(
      'Any text',
    )
  })

  it('counts optional fields and flags a bad name', () => {
    renderField([{ name: 'Risk', type: 'boolean' }])
    expect(screen.getByText(/lower case letters/)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Field 1 required'))
    expect(screen.getByText('1 of 24 optional fields.')).toBeInTheDocument()
  })
})
