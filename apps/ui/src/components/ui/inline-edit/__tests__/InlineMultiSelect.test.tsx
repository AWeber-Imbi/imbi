import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'

import { InlineMultiSelect } from '../InlineMultiSelect'

const options = [
  { label: 'Alpha', value: 'a' },
  { label: 'Beta', value: 'b' },
  { label: 'Charlie', value: 'c' },
]

describe('InlineMultiSelect', () => {
  it('renders current labels', () => {
    render(
      <InlineMultiSelect
        onCommit={vi.fn()}
        options={options}
        values={['a', 'b']}
      />,
    )
    expect(screen.getByText('Alpha, Beta')).toBeInTheDocument()
  })

  it('commits the new list when the popover closes with changes', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(
      <InlineMultiSelect
        onCommit={onCommit}
        options={options}
        values={['a']}
      />,
    )
    await userEvent.click(screen.getByText('Alpha'))
    await userEvent.click(await screen.findByLabelText('Beta'))
    await userEvent.keyboard('{Escape}')
    await waitFor(() =>
      expect(onCommit).toHaveBeenCalledWith(expect.arrayContaining(['a', 'b'])),
    )
  })
})
