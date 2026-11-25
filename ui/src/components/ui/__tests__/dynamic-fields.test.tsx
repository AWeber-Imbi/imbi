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

describe('validateDynamicFields value checks', () => {
  const schema = {
    properties: {
      budget: toDynamicField({ pattern: '^\\d+(\\.\\d{2})?$', type: 'string' }),
      owners: toDynamicField({
        items: { format: 'uuid', type: 'string' },
        type: 'array',
      }),
      rate: toDynamicField({ multipleOf: 0.01, type: 'number' }),
    },
  }

  it('accepts valid values', () => {
    expect(
      validateDynamicFields(schema, {
        budget: '1250.00',
        owners: ['a8098c1a-f86e-11da-bd1a-00112444be1e'],
        rate: 19.99,
      }),
    ).toEqual({})
  })

  it('refuses a value that does not match the pattern', () => {
    expect(validateDynamicFields(schema, { budget: '12.5' })).toHaveProperty(
      'budget',
    )
  })

  it('refuses an item that is not a UUID', () => {
    expect(validateDynamicFields(schema, { owners: ['nope'] })).toHaveProperty(
      'owners/0',
    )
  })

  it('refuses a rate that is not a multiple of 0.01', () => {
    expect(validateDynamicFields(schema, { rate: 1.005 })).toHaveProperty(
      'rate',
    )
  })
})

describe('validateDynamicFields with a Python-only pattern', () => {
  it('leaves the check to the API', () => {
    const schema = {
      properties: {
        code: toDynamicField({ pattern: '(?P<n>x)', type: 'string' }),
      },
    }
    expect(validateDynamicFields(schema, { code: 'y' })).toEqual({})
  })
})
