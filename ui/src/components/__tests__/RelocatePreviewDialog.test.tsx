import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { LifecyclePreviewEntry } from '@/types'

import { RelocatePreviewDialog } from '../RelocatePreviewDialog'

const entries: LifecyclePreviewEntry[] = [
  {
    current_target: {
      display: 'apis/my-api',
      identifier: 'apis/my-api',
      link_key: 'github-repository',
    },
    next_target: {
      display: 'workers/my-api',
      identifier: 'workers/my-api',
      link_key: 'github-repository',
    },
    plugin_id: 'p-a',
    plugin_slug: 'gh-a',
    would_relocate: true,
  },
]

describe('RelocatePreviewDialog', () => {
  it('renders each relocating plugin with its current and next target', () => {
    render(
      <RelocatePreviewDialog
        entries={entries}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
        open
      />,
    )

    expect(screen.getByText('gh-a')).toBeInTheDocument()
    expect(screen.getByText('apis/my-api')).toBeInTheDocument()
    expect(screen.getByText('workers/my-api')).toBeInTheDocument()
  })

  it('confirms without the move by default (checkbox unchecked)', () => {
    const onConfirm = vi.fn()
    render(
      <RelocatePreviewDialog
        entries={entries}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
        open
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(onConfirm).toHaveBeenCalledWith(false)
  })

  it('confirms with the move when the checkbox is opted in', () => {
    const onConfirm = vi.fn()
    render(
      <RelocatePreviewDialog
        entries={entries}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
        open
      />,
    )

    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(onConfirm).toHaveBeenCalledWith(true)
  })

  it('falls back to the identifier when a target has no display label', () => {
    render(
      <RelocatePreviewDialog
        entries={[
          {
            ...entries[0],
            next_target: {
              display: null,
              identifier: 'workers/my-api',
              link_key: 'github-repository',
            },
          },
        ]}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
        open
      />,
    )

    expect(screen.getByText('workers/my-api')).toBeInTheDocument()
  })

  it('invokes onCancel from the Cancel button', () => {
    const onCancel = vi.fn()
    render(
      <RelocatePreviewDialog
        entries={entries}
        onCancel={onCancel}
        onConfirm={vi.fn()}
        open
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalled()
  })
})
