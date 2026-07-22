import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { Keystroke } from '../keystroke'

describe('Keystroke', () => {
  it('renders a single key', () => {
    render(<Keystroke value="/" />)
    expect(screen.getByText('/')).toBeInTheDocument()
  })

  it('renders each key in a kbd element', () => {
    const { container } = render(<Keystroke isMac={false} value="Ctrl+A" />)
    const kbds = container.querySelectorAll('kbd')
    expect(kbds).toHaveLength(2)
  })

  it('handles extra whitespace and mixed casing in key names', () => {
    render(<Keystroke isMac={false} value="  CTRL  +  z  " />)
    expect(screen.getByText('Ctrl')).toBeInTheDocument()
    expect(screen.getByText('z')).toBeInTheDocument()
  })

  describe('on Mac', () => {
    it('renders Ctrl as ⌘', () => {
      render(<Keystroke isMac={true} value="Ctrl+Shift+A" />)
      expect(screen.getByText('⌘')).toBeInTheDocument()
      expect(screen.getByText('⇧')).toBeInTheDocument()
      expect(screen.getByText('A')).toBeInTheDocument()
    })

    it('renders alt as ⌥', () => {
      render(<Keystroke isMac={true} value="Alt+X" />)
      expect(screen.getByText('⌥')).toBeInTheDocument()
    })
  })

  describe('on non-Mac', () => {
    it('renders Ctrl as Ctrl', () => {
      render(<Keystroke isMac={false} value="Ctrl+Shift+A" />)
      expect(screen.getByText('Ctrl')).toBeInTheDocument()
      expect(screen.getByText('Shift')).toBeInTheDocument()
      expect(screen.getByText('A')).toBeInTheDocument()
    })

    it('renders alt as Alt', () => {
      render(<Keystroke isMac={false} value="Alt+X" />)
      expect(screen.getByText('Alt')).toBeInTheDocument()
    })
  })
})
