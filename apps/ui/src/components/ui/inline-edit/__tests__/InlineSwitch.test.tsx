import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineSwitch } from '../InlineSwitch'

describe('InlineSwitch', () => {
  it('commits the toggled value', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineSwitch value={false} onCommit={onCommit} />)
    await userEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith(true))
  })

  it('is disabled when readOnly', () => {
    render(<InlineSwitch value readOnly onCommit={vi.fn()} />)
    expect(screen.getByRole('switch')).toBeDisabled()
  })
})
