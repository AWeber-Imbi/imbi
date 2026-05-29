import { useRef, useState } from 'react'

import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { useAssistantShortcut } from '../useAssistantShortcut'

function Harness() {
  const [expanded, setExpanded] = useState(false)
  const [focused, setFocused] = useState(false)
  const [value, setValue] = useState('')
  const ref = useRef<HTMLInputElement>(null)
  useAssistantShortcut(ref, expanded, setExpanded)
  return (
    <div>
      <span data-testid="expanded">{expanded ? 'open' : 'closed'}</span>
      <input
        aria-label="assistant"
        data-testid="assistant-input"
        onBlur={() => setFocused(false)}
        onChange={(e) => setValue(e.target.value)}
        onFocus={() => setFocused(true)}
        ref={ref}
        type="text"
        value={value}
      />
      {!value && !focused && <span data-testid="badge">⌘⇧A</span>}
    </div>
  )
}

describe('useAssistantShortcut', () => {
  it('focuses the assistant input when Ctrl+Shift+A is pressed', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.keyboard('{Control>}{Shift>}A{/Shift}{/Control}')
    expect(screen.getByTestId('assistant-input')).toHaveFocus()
  })

  it('expands the bar if it is collapsed', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(screen.getByTestId('expanded')).toHaveTextContent('closed')
    await user.keyboard('{Control>}{Shift>}A{/Shift}{/Control}')
    expect(screen.getByTestId('expanded')).toHaveTextContent('open')
  })

  it('hides the badge when the input is focused', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(screen.getByTestId('badge')).toBeInTheDocument()
    await user.click(screen.getByTestId('assistant-input'))
    expect(screen.queryByTestId('badge')).not.toBeInTheDocument()
  })

  it('hides the badge when the input has a value', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByTestId('assistant-input'))
    await user.keyboard('hello')
    await user.tab()
    expect(screen.queryByTestId('badge')).not.toBeInTheDocument()
  })
})
