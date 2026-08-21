import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { render } from '@/test/utils'

import { DriftIndicator } from './DriftIndicator'

describe('DriftIndicator', () => {
  it('names a true verdict as drift', () => {
    render(<DriftIndicator drift={true} />)
    expect(
      screen.getByRole('img', { name: 'Drift Detected' }),
    ).toBeInTheDocument()
  })

  it('names an explicit false verdict as no drift', () => {
    render(<DriftIndicator drift={false} />)
    expect(
      screen.getByRole('img', { name: 'No Drift Detected' }),
    ).toBeInTheDocument()
  })

  it('fails closed on an unanswered commit', () => {
    // The fleet rule: a commit is clean only when CI explicitly said
    // false. null and undefined both mean "never answered" and must
    // display as drifted, not as clean.
    for (const drift of [null, undefined]) {
      const { unmount } = render(<DriftIndicator drift={drift} />)
      expect(
        screen.getByRole('img', { name: 'Drift Detected' }),
      ).toBeInTheDocument()
      unmount()
    }
  })
})
