import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineDisplay } from '../InlineDisplay'

describe('InlineDisplay', () => {
  it('renders children when value is non-empty', () => {
    render(
      <InlineDisplay hasValue onClick={vi.fn()}>
        Alpha
      </InlineDisplay>,
    )
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('renders "Add…" placeholder when hasValue is false', () => {
    render(<InlineDisplay hasValue={false} onClick={vi.fn()} />)
    expect(screen.getByText(/add/i)).toBeInTheDocument()
  })

  it('fires onClick when the row is clicked', async () => {
    const onClick = vi.fn()
    render(
      <InlineDisplay hasValue onClick={onClick}>
        Alpha
      </InlineDisplay>,
    )
    await userEvent.click(screen.getByText('Alpha'))
    expect(onClick).toHaveBeenCalled()
  })

  it('does not fire onClick when readOnly', async () => {
    const onClick = vi.fn()
    render(
      <InlineDisplay hasValue readOnly onClick={onClick}>
        Alpha
      </InlineDisplay>,
    )
    await userEvent.click(screen.getByText('Alpha'))
    expect(onClick).not.toHaveBeenCalled()
  })
})
