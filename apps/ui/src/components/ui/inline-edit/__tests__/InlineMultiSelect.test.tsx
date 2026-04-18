import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineMultiSelect } from '../InlineMultiSelect'

const options = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' },
  { value: 'c', label: 'Charlie' },
]

describe('InlineMultiSelect', () => {
  it('renders current labels', () => {
    render(
      <InlineMultiSelect
        values={['a', 'b']}
        options={options}
        onCommit={vi.fn()}
      />,
    )
    expect(screen.getByText('Alpha, Beta')).toBeInTheDocument()
  })

  it('commits the new list when the popover closes with changes', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(
      <InlineMultiSelect
        values={['a']}
        options={options}
        onCommit={onCommit}
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
