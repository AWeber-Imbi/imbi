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
  it('keeps a newline typed before existing text', async () => {
    render(<ControlledTextarea />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    await userEvent.type(textarea, 'existing')
    textarea.setSelectionRange(0, 0)
    await userEvent.type(textarea, '{Enter}', {
      initialSelectionEnd: 0,
      initialSelectionStart: 0,
    })
    expect(textarea).toHaveValue('\nexisting')
    expect(textarea.selectionStart).toBe(1)
  })

  it('preserves interior and trailing whitespace', async () => {
    render(<ControlledTextarea />)
    const textarea = screen.getByRole('textbox')
    await userEvent.type(textarea, 'line one line two ')
    expect(textarea).toHaveValue('line one line two ')
  })
})
