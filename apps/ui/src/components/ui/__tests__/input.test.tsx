import { useState } from 'react'

import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { Input } from '../input'

function ControlledInput({ type }: { type?: string }) {
  const [value, setValue] = useState('')
  return (
    <Input
      onChange={(e) => setValue(e.target.value)}
      type={type}
      value={value}
    />
  )
}

describe('Input', () => {
  it('strips leading whitespace as the user types', async () => {
    render(<ControlledInput />)
    const input = screen.getByRole('textbox')
    await userEvent.type(input, '   Acme')
    expect(input).toHaveValue('Acme')
  })

  it('preserves interior and trailing whitespace', async () => {
    render(<ControlledInput />)
    const input = screen.getByRole('textbox')
    await userEvent.type(input, 'Acme Corp ')
    expect(input).toHaveValue('Acme Corp ')
  })

  it('strips leading whitespace from pasted text', async () => {
    render(<ControlledInput />)
    const input = screen.getByRole('textbox')
    input.focus()
    await userEvent.paste('   pasted')
    expect(input).toHaveValue('pasted')
  })

  it('leaves password values untouched', async () => {
    render(<ControlledInput type="password" />)
    // Password inputs expose no textbox role; query by the rendered element.
    const input = document.querySelector('input[type="password"]')!
    ;(input as HTMLInputElement).focus()
    await userEvent.type(input as HTMLInputElement, ' secret')
    expect(input).toHaveValue(' secret')
  })
})
