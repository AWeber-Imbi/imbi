import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen, waitFor } from '@/test/utils'

import { InlineSwitch } from '../InlineSwitch'

describe('InlineSwitch', () => {
  it('commits the toggled value', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineSwitch onCommit={onCommit} value={false} />)
    await userEvent.click(screen.getByText('False'))
    await userEvent.click(await screen.findByRole('switch'))
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith(true))
  })

  it('does not enter edit mode when readOnly', async () => {
    render(<InlineSwitch onCommit={vi.fn()} readOnly value />)
    await userEvent.click(screen.getByText('True'))
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
  })
})
