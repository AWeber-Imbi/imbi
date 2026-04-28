import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'

import { InlineSelect } from '../InlineSelect'

const options = [
  { label: 'Alpha', value: 'a' },
  { label: 'Beta', value: 'b' },
]

describe('InlineSelect', () => {
  it('renders label for current value', () => {
    render(<InlineSelect onCommit={vi.fn()} options={options} value="a" />)
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('commits when a different option is chosen', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineSelect onCommit={onCommit} options={options} value="a" />)
    await userEvent.click(screen.getByText('Alpha'))
    await userEvent.click(await screen.findByRole('option', { name: 'Beta' }))
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('b'))
  })
})
