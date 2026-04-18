import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineSelect } from '../InlineSelect'

const options = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' },
]

describe('InlineSelect', () => {
  it('renders label for current value', () => {
    render(<InlineSelect value="a" options={options} onCommit={vi.fn()} />)
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('commits when a different option is chosen', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineSelect value="a" options={options} onCommit={onCommit} />)
    await userEvent.click(screen.getByText('Alpha'))
    await userEvent.click(await screen.findByRole('option', { name: 'Beta' }))
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('b'))
  })
})
