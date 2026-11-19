import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { FormField } from '../form-field'

describe('FormField', () => {
  it('links the input to the error via htmlFor', () => {
    render(
      <FormField error="Required" htmlFor="name" label="Name" touched>
        <input id="name" />
      </FormField>,
    )
    const input = screen.getByRole('textbox')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAttribute('aria-describedby', 'name-error')
    expect(input).toHaveAccessibleDescription('Required')
  })

  it('links the input to the error without htmlFor', () => {
    render(
      <FormField error="Required" label="Name" touched>
        <input />
      </FormField>,
    )
    const input = screen.getByRole('textbox')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Required')
  })

  it('adds no error attributes when untouched', () => {
    render(
      <FormField error="Required" label="Name">
        <input />
      </FormField>,
    )
    const input = screen.getByRole('textbox')
    expect(input).not.toHaveAttribute('aria-invalid')
    expect(input).not.toHaveAttribute('aria-describedby')
  })
})
