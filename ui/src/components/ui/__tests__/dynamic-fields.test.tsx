import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import {
  DynamicFormFields,
  toDynamicField,
  validateDynamicFields,
} from '../dynamic-fields'

describe('DynamicFormFields', () => {
  it('connects a boolean field error to its checkbox', () => {
    render(
      <DynamicFormFields
        data={{}}
        errors={{ public: 'must be boolean' }}
        onChange={() => {}}
        schema={{ properties: { public: { type: 'boolean' } } }}
      />,
    )

    const checkbox = screen.getByRole('checkbox', { name: 'Public' })
    expect(checkbox).toHaveAttribute('aria-invalid', 'true')
    expect(checkbox).toHaveAccessibleDescription('must be boolean')
  })

  it('gives an array field an array value', () => {
    const onChange = vi.fn()
    const field = toDynamicField({
      items: { enum: ['api', 'worker'], type: 'string' },
      type: 'array',
    })
    const schema = { properties: { parts: field }, required: ['parts'] }
    render(
      <DynamicFormFields
        data={{}}
        errors={{}}
        onChange={onChange}
        schema={schema}
      />,
    )
    const input = screen.getByLabelText(/Parts/)
    fireEvent.change(input, { target: { value: '["api"]' } })
    expect(onChange).toHaveBeenLastCalledWith('parts', ['api'])
    fireEvent.change(input, { target: { value: '["api"' } })
    expect(onChange).toHaveBeenLastCalledWith('parts', '["api"')
    expect(validateDynamicFields(schema, { parts: ['api'] })).toEqual({})
    expect(validateDynamicFields(schema, { parts: ['db'] })).toHaveProperty(
      'parts/0',
    )
  })
})
