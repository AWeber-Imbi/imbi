import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineText } from '../InlineText'

describe('InlineText', () => {
  it('renders value in display mode', () => {
    render(<InlineText value="Alpha" onCommit={vi.fn()} />)
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('enters edit mode on click and autofocuses', async () => {
    render(<InlineText value="Alpha" onCommit={vi.fn()} />)
    await userEvent.click(screen.getByText('Alpha'))
    const input = screen.getByRole('textbox')
    expect(input).toHaveFocus()
    expect(input).toHaveValue('Alpha')
  })

  it('commits on Enter with the edited value', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineText value="Alpha" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('Alpha'))
    const input = screen.getByRole('textbox')
    await userEvent.clear(input)
    await userEvent.type(input, 'Beta{Enter}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('Beta'))
  })

  it('cancels on Escape and does not commit', async () => {
    const onCommit = vi.fn()
    render(<InlineText value="Alpha" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('Alpha'))
    await userEvent.keyboard('{Escape}')
    expect(onCommit).not.toHaveBeenCalled()
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('renders "Add…" when value is null and is editable', async () => {
    render(<InlineText value={null} onCommit={vi.fn()} />)
    expect(screen.getByText(/add/i)).toBeInTheDocument()
  })

  it('is not interactive when readOnly', async () => {
    render(<InlineText value="Alpha" onCommit={vi.fn()} readOnly />)
    await userEvent.click(screen.getByText('Alpha'))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})
