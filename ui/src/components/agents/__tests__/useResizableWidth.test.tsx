import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'

import { useResizableWidth } from '../useResizableWidth'

function Sidebar() {
  const { handleProps, width } = useResizableWidth('test:width', 250, 200, 280)
  return (
    <aside data-testid="sidebar" style={{ width }}>
      <div {...handleProps} />
    </aside>
  )
}

describe('useResizableWidth', () => {
  it('changes the width with the arrow keys and keeps it', () => {
    render(<Sidebar />)
    const handle = screen.getByRole('separator', { name: 'Resize sidebar' })
    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    expect(screen.getByTestId('sidebar')).toHaveStyle({ width: '266px' })
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      'test:width',
      '266',
    )
    // The maximum stops the second step.
    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    expect(handle).toHaveAttribute('aria-valuenow', '280')
  })

  it('follows the pointer during a drag and stops at the minimum', () => {
    render(<Sidebar />)
    const handle = screen.getByRole('separator', { name: 'Resize sidebar' })
    handle.setPointerCapture = () => {}
    fireEvent.pointerDown(handle, { clientX: 250, pointerId: 1 })
    fireEvent.pointerMove(handle, { clientX: 230, pointerId: 1 })
    expect(handle).toHaveAttribute('aria-valuenow', '230')
    fireEvent.pointerMove(handle, { clientX: 20, pointerId: 1 })
    expect(handle).toHaveAttribute('aria-valuenow', '200')
    // A move after the drag ends changes nothing.
    fireEvent.lostPointerCapture(handle, { pointerId: 1 })
    fireEvent.pointerMove(handle, { clientX: 260, pointerId: 1 })
    expect(handle).toHaveAttribute('aria-valuenow', '200')
  })

  it('puts a stored width that is out of range back in range', () => {
    vi.mocked(window.localStorage.getItem).mockReturnValueOnce('9000')
    render(<Sidebar />)
    expect(screen.getByTestId('sidebar')).toHaveStyle({ width: '280px' })
  })
})
