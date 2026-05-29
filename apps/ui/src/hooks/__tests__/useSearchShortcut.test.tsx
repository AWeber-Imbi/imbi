import { useRef, useState } from 'react'

import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { useSearchShortcut } from '../useSearchShortcut'

function Harness({ disabled = false }: { disabled?: boolean }) {
  const [focused, setFocused] = useState(false)
  const [value, setValue] = useState('')
  const ref = useRef<HTMLInputElement>(null)
  useSearchShortcut(ref)
  return (
    <div>
      <input aria-label="other" data-testid="other-input" type="text" />
      <input
        aria-label="search"
        data-testid="search-input"
        disabled={disabled}
        onBlur={() => setFocused(false)}
        onChange={(e) => setValue(e.target.value)}
        onFocus={() => setFocused(true)}
        ref={ref}
        type="text"
        value={value}
      />
      {!value && !focused && <span data-testid="badge">/</span>}
    </div>
  )
}

describe('useSearchShortcut', () => {
  it('focuses the search input when / is pressed', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.keyboard('/')
    expect(screen.getByTestId('search-input')).toHaveFocus()
  })

  it('does not focus when already typing in another input', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const other = screen.getByTestId('other-input')
    await user.click(other)
    await user.keyboard('/')
    expect(screen.getByTestId('search-input')).not.toHaveFocus()
    expect(other).toHaveFocus()
  })

  it('does not focus when the search input is disabled', async () => {
    const user = userEvent.setup()
    render(<Harness disabled />)
    await user.keyboard('/')
    expect(screen.getByTestId('search-input')).not.toHaveFocus()
  })

  it('hides the badge when the input is focused', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(screen.getByTestId('badge')).toBeInTheDocument()
    await user.click(screen.getByTestId('search-input'))
    expect(screen.queryByTestId('badge')).not.toBeInTheDocument()
  })

  it('hides the badge when the input has a value', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByTestId('search-input'))
    await user.keyboard('foo')
    await user.tab()
    expect(screen.queryByTestId('badge')).not.toBeInTheDocument()
  })
})
