import { useState } from 'react'

import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { Textarea } from '../textarea'

function ControlledTextarea() {
  const [value, setValue] = useState('')
  return <Textarea onChange={(e) => setValue(e.target.value)} value={value} />
}

describe('Textarea', () => {
  it('strips leading whitespace as the user types', async () => {
    render(<ControlledTextarea />)
    const textarea = screen.getByRole('textbox')
    await userEvent.type(textarea, '   A description')
    expect(textarea).toHaveValue('A description')
  })

  it('preserves interior and trailing whitespace', async () => {
    render(<ControlledTextarea />)
    const textarea = screen.getByRole('textbox')
    await userEvent.type(textarea, 'line one line two ')
    expect(textarea).toHaveValue('line one line two ')
  })
})
