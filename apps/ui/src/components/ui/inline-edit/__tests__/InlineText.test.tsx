import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'

import { InlineText } from '../InlineText'

describe('InlineText', () => {
  it('renders value in display mode', () => {
    render(<InlineText onCommit={vi.fn()} value="Alpha" />)
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('enters edit mode on click and autofocuses', async () => {
    render(<InlineText onCommit={vi.fn()} value="Alpha" />)
    await userEvent.click(screen.getByText('Alpha'))
    const input = screen.getByRole('textbox')
    expect(input).toHaveFocus()
    expect(input).toHaveValue('Alpha')
  })

  it('commits on Enter with the edited value', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineText onCommit={onCommit} value="Alpha" />)
    await userEvent.click(screen.getByText('Alpha'))
    const input = screen.getByRole('textbox')
    await userEvent.clear(input)
    await userEvent.type(input, 'Beta{Enter}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('Beta'))
  })

  it('cancels on Escape and does not commit', async () => {
    const onCommit = vi.fn()
    render(<InlineText onCommit={onCommit} value="Alpha" />)
    await userEvent.click(screen.getByText('Alpha'))
    await userEvent.keyboard('{Escape}')
    expect(onCommit).not.toHaveBeenCalled()
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('renders "Add…" when value is null and is editable', async () => {
    render(<InlineText onCommit={vi.fn()} value={null} />)
    expect(screen.getByText(/add/i)).toBeInTheDocument()
  })

  it('is not interactive when readOnly', async () => {
    render(<InlineText onCommit={vi.fn()} readOnly value="Alpha" />)
    await userEvent.click(screen.getByText('Alpha'))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})
