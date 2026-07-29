import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'

import { InlineDate } from '../InlineDate'

describe('InlineDate', () => {
  it('opens the calendar and commits an ISO date on day select', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineDate mode="date" onCommit={onCommit} value="2026-05-10" />)
    await userEvent.click(screen.getByText(/2026/))
    const day15 = await screen.findByRole('button', { name: /15/ })
    await userEvent.click(day15)
    await waitFor(() =>
      expect(onCommit).toHaveBeenCalledWith(
        expect.stringMatching(/2026-05-15/),
      ),
    )
  })

  // A date-only value names a calendar day. Routing it through
  // toISOString() shifted the day in one direction on display and the
  // other on commit, so both ends are pinned here.
  it('displays a date-only value on the day it names', () => {
    render(<InlineDate mode="date" onCommit={vi.fn()} value="2026-05-10" />)
    const expected = new Date(2026, 4, 10).toLocaleDateString()
    expect(screen.getByText(expected)).toBeInTheDocument()
  })

  it('commits the selected day without shifting it', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineDate mode="date" onCommit={onCommit} value="2026-05-10" />)
    await userEvent.click(screen.getByText(/2026/))
    await userEvent.click(await screen.findByRole('button', { name: /15/ }))
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('2026-05-15'))
  })

  it('still commits a full ISO instant in date-time mode', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(
      <InlineDate
        mode="date-time"
        onCommit={onCommit}
        value="2026-05-10T12:00:00Z"
      />,
    )
    await userEvent.click(screen.getByText(/2026/))
    await userEvent.click(await screen.findByRole('button', { name: /15/ }))
    await waitFor(() =>
      expect(onCommit).toHaveBeenCalledWith(
        expect.stringMatching(/^2026-05-1[45]T.*Z$/),
      ),
    )
  })
})
