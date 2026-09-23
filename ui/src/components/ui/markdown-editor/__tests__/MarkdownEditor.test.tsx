import { useState } from 'react'

import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { render } from '@/test/utils'

import { MarkdownEditor } from '../MarkdownEditor'

function Harness({
  disabled,
  initial = '',
}: {
  disabled?: boolean
  initial?: string
}) {
  const [value, setValue] = useState(initial)
  return (
    <MarkdownEditor
      aria-label="Notes"
      disabled={disabled}
      onChange={setValue}
      value={value}
    />
  )
}

function select(start: number, end: number): HTMLTextAreaElement {
  const textarea = screen.getByRole<HTMLTextAreaElement>('textbox', {
    name: 'Notes',
  })
  textarea.focus()
  textarea.setSelectionRange(start, end)
  return textarea
}

describe('MarkdownEditor', () => {
  it('wraps the selection when a toolbar button is clicked', async () => {
    const user = userEvent.setup()
    render(<Harness initial="make this loud" />)
    const textarea = select(10, 14)

    await user.click(screen.getByRole('button', { name: 'Bold' }))

    expect(textarea).toHaveValue('make this **loud**')
    expect(textarea.selectionStart).toBe(12)
    expect(textarea.selectionEnd).toBe(16)
  })

  it('prefixes lines from the toolbar', async () => {
    const user = userEvent.setup()
    render(<Harness initial={'one\ntwo'} />)
    const textarea = select(0, 7)

    await user.click(screen.getByRole('button', { name: 'Numbered list' }))

    expect(textarea).toHaveValue('1. one\n2. two')
  })

  it('applies Cmd-B and Ctrl-K shortcuts', async () => {
    const user = userEvent.setup()
    render(<Harness initial="docs" />)
    const textarea = select(0, 4)

    await user.keyboard('{Meta>}b{/Meta}')
    expect(textarea).toHaveValue('**docs**')

    select(2, 6)
    await user.keyboard('{Control>}k{/Control}')
    expect(textarea).toHaveValue('**[docs](url)**')
  })

  it('renders markdown in the Preview tab and hides the toolbar', async () => {
    const user = userEvent.setup()
    render(<Harness initial={'### Highlights\n- faster'} />)

    await user.click(screen.getByRole('tab', { name: 'Preview' }))

    expect(
      screen.getByRole('heading', { level: 3, name: 'Highlights' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Write' }))
    expect(screen.getByRole('toolbar')).toBeInTheDocument()
  })

  it('shows an empty state when there is nothing to preview', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.click(screen.getByRole('tab', { name: 'Preview' }))

    expect(screen.getByText('Nothing to preview')).toBeInTheDocument()
  })

  it('disables the textarea and the toolbar', () => {
    render(<Harness disabled initial="locked" />)

    expect(screen.getByRole('textbox', { name: 'Notes' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Bold' })).toBeDisabled()
  })
})
