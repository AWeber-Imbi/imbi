import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'

import { InlineSwitch } from '../InlineSwitch'

describe('InlineSwitch', () => {
  it('commits the toggled value', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineSwitch onCommit={onCommit} value={false} />)
    await userEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith(true))
  })

  it('is disabled when readOnly', () => {
    render(<InlineSwitch onCommit={vi.fn()} readOnly value />)
    expect(screen.getByRole('switch')).toBeDisabled()
  })
})
