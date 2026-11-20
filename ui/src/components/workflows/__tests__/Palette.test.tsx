import { beforeEach, describe, expect, it } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'

import { Palette } from '../Palette'

describe('Palette', () => {
  beforeEach(() => localStorage.clear())

  it('keeps focus on the toggle when it collapses and expands', () => {
    render(<Palette onAdd={() => {}} types={[]} />)
    expect(document.activeElement).toBe(document.body)

    fireEvent.click(screen.getByRole('button', { name: 'Collapse steps' }))
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'Expand steps' }),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Expand steps' }))
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'Collapse steps' }),
    )
  })
})
