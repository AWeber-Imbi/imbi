import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { render } from '@/test/utils'

import { CiStatusDot } from './CiStatusDot'

describe('CiStatusDot', () => {
  it('names each CI state in words, not just colour', () => {
    for (const [status, label] of [
      ['pass', 'CI passed'],
      ['fail', 'CI failed'],
      ['warn', 'CI passed with warnings'],
      ['unknown', 'CI status unknown'],
    ] as const) {
      const { unmount } = render(<CiStatusDot status={status} />)
      expect(screen.getByRole('img', { name: label })).toBeInTheDocument()
      unmount()
    }
  })

  it('distinguishes "nothing could answer" from "unknown"', () => {
    // #211: a releasable-only project has no environments and so no
    // synced deployment history to read a status from. Rendering that as
    // "unknown" claimed a question had been asked and come back empty,
    // which made a green build look unverified.
    render(<CiStatusDot status="not_applicable" />)
    expect(
      screen.getByRole('img', {
        name: 'No CI status — this project has no environments',
      }),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('CI status unknown')).toBeNull()
  })

  it('falls back to unknown for a missing status', () => {
    render(<CiStatusDot status={null} />)
    expect(screen.getByLabelText('CI status unknown')).toBeInTheDocument()
  })

  it('falls back to unknown for a status it does not recognize', () => {
    render(<CiStatusDot status="unrecognized" />)
    expect(screen.getByLabelText('CI status unknown')).toBeInTheDocument()
  })
})
