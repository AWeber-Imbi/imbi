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
})
