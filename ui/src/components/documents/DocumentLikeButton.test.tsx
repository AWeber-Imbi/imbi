import { fireEvent, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'

import { DocumentLikeButton } from './DocumentLikeButton'
import type { DocumentLike } from './useDocumentLike'

function likeState(overrides: Partial<DocumentLike> = {}): DocumentLike {
  return {
    like_count: 11,
    liked_by_me: false,
    toggle: vi.fn(),
    ...overrides,
  }
}

function renderButton(like: DocumentLike, variant?: 'pill' | 'toolbar') {
  return render(
    <DocumentLikeButton
      documentId="doc-1"
      like={like}
      orgSlug="acme"
      variant={variant}
    />,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('DocumentLikeButton', () => {
  it('names the gesture and shows the count in the pill treatment', () => {
    renderButton(likeState(), 'pill')

    const button = screen.getByRole('button', { name: 'Like this document' })
    expect(button).toHaveTextContent('Like')
    expect(button).toHaveTextContent('11')
    expect(button).toHaveAttribute('aria-pressed', 'false')
  })

  it('reads as pressed once liked', () => {
    renderButton(likeState({ like_count: 12, liked_by_me: true }), 'pill')

    const button = screen.getByRole('button', { name: 'Remove like' })
    expect(button).toHaveTextContent('Liked')
    expect(button).toHaveAttribute('aria-pressed', 'true')
  })

  it('hides a zero count in the toolbar treatment', () => {
    renderButton(likeState({ like_count: 0 }))

    expect(
      screen.getByRole('button', { name: 'Like this document' }),
    ).not.toHaveTextContent('0')
  })

  it('toggles on click', () => {
    const like = likeState()
    renderButton(like, 'pill')

    fireEvent.click(screen.getByRole('button'))

    expect(like.toggle).toHaveBeenCalledOnce()
  })

  it('names the likers after a deliberate hover, collapsing the tail', async () => {
    vi.spyOn(endpoints, 'listDocumentLikers').mockResolvedValue(
      Array.from({ length: 10 }, (_, index) => ({
        display_name: index === 0 ? 'Gavin Roy' : '',
        liked_at: '2026-07-24T12:00:00Z',
        principal: `person-${index}@example.com`,
      })),
    )
    renderButton(likeState(), 'pill')

    fireEvent.mouseEnter(screen.getByRole('button'))

    await waitFor(() => expect(screen.getByText('Liked by')).toBeVisible())
    expect(screen.getByText('Gavin Roy')).toBeInTheDocument()
    expect(screen.getByText('person-7@example.com')).toBeInTheDocument()
    expect(screen.queryByText('person-8@example.com')).not.toBeInTheDocument()
    expect(screen.getByText('and 2 more')).toBeInTheDocument()
  })

  it('costs no request for a cursor that sweeps straight past', () => {
    vi.useFakeTimers()
    const list = vi.spyOn(endpoints, 'listDocumentLikers').mockResolvedValue([])
    renderButton(likeState(), 'pill')

    const button = screen.getByRole('button')
    fireEvent.mouseEnter(button)
    fireEvent.mouseLeave(button)
    vi.advanceTimersByTime(1000)

    expect(list).not.toHaveBeenCalled()
  })
})
