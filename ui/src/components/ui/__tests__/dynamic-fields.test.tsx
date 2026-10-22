import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DynamicFormFields } from '../dynamic-fields'

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
})
