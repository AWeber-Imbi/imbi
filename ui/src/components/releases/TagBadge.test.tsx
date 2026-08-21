import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { render } from '@/test/utils'

import { TagBadge } from './TagBadge'

describe('TagBadge', () => {
  it('names the tag pointing at the commit', () => {
    render(<TagBadge tag="v2.6.1" />)
    expect(screen.getByText('v2.6.1')).toBeInTheDocument()
  })

  it('renders nothing for an untagged commit', () => {
    // Most commits are not directly tagged — no badge, no placeholder.
    for (const tag of [null, undefined, '']) {
      const { container, unmount } = render(<TagBadge tag={tag} />)
      expect(container).toBeEmptyDOMElement()
      unmount()
    }
  })
})
