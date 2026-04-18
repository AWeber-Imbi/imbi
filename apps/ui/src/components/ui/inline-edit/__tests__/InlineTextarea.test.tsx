import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineTextarea } from '../InlineTextarea'

describe('InlineTextarea', () => {
  it('commits on Ctrl+Enter', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineTextarea value="hi" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('hi'))
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement
    await userEvent.clear(ta)
    await userEvent.type(ta, 'there')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('there'))
  })

  it('commits on Cmd+Enter (macOS Meta key)', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineTextarea value="hi" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('hi'))
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement
    await userEvent.clear(ta)
    await userEvent.type(ta, 'there')
    await userEvent.keyboard('{Meta>}{Enter}{/Meta}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('there'))
  })

  it('plain Enter inserts a newline and does not commit', async () => {
    const onCommit = vi.fn()
    render(<InlineTextarea value="hi" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('hi'))
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement
    await userEvent.type(ta, '{Enter}x')
    expect(ta.value).toContain('\n')
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('Escape cancels', async () => {
    const onCommit = vi.fn()
    render(<InlineTextarea value="hi" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('hi'))
    await userEvent.type(screen.getByRole('textbox'), ' edits')
    await userEvent.keyboard('{Escape}')
    expect(onCommit).not.toHaveBeenCalled()
    expect(screen.getByText('hi')).toBeInTheDocument()
  })
})
