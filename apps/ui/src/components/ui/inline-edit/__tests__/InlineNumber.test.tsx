import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'

import { InlineNumber } from '../InlineNumber'

describe('InlineNumber', () => {
  it('commits parsed number on Enter', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineNumber onCommit={onCommit} value={10} />)
    await userEvent.click(screen.getByText('10'))
    const input = screen.getByRole('spinbutton')
    await userEvent.clear(input)
    await userEvent.type(input, '42{Enter}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith(42))
  })

  it('commits null when cleared', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineNumber onCommit={onCommit} value={10} />)
    await userEvent.click(screen.getByText('10'))
    const input = screen.getByRole('spinbutton')
    await userEvent.clear(input)
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith(null))
  })
})
