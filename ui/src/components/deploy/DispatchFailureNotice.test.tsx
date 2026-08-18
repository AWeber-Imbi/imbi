import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { render } from '@/test/utils'

import {
  dispatchFailureDetail,
  DispatchFailureNotice,
} from './DispatchFailureNotice'

const DETAIL =
  "The configured Release workflow 'release.yml' does not exist in this " +
  "project's repository, so there is nothing to dispatch."

describe('dispatchFailureDetail', () => {
  it('carries the detail for the statuses the API explains with', () => {
    // 400 (bad workflow), 403 (disabled or unpermitted), 409 (blocked or
    // already in flight), 502 (the remote answered something unhelpful).
    for (const status of [400, 403, 409, 422, 502]) {
      expect(
        dispatchFailureDetail(new ApiError(status, 'x', { detail: DETAIL })),
      ).toBe(DETAIL)
    }
  })

  it('leaves a 500 to the toast', () => {
    // An Imbi bug has no sentence an operator can act on; pinning it to
    // the form would put noise where the fix belongs.
    expect(
      dispatchFailureDetail(new ApiError(500, 'x', { detail: 'boom' })),
    ).toBeNull()
  })

  it('leaves a transport failure to the toast', () => {
    expect(dispatchFailureDetail(new Error('network down'))).toBeNull()
  })

  it('answers null when the body carries no detail at all', () => {
    expect(dispatchFailureDetail(new ApiError(400, 'x', {}))).toBeNull()
  })
})

describe('DispatchFailureNotice', () => {
  it('renders nothing without an error', () => {
    const { container } = render(
      <DispatchFailureNotice action="release" error={null} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('names the flow and says nothing was dispatched', () => {
    render(<DispatchFailureNotice action="promote" error={DETAIL} />)
    expect(screen.getByText('Promote refused')).toBeInTheDocument()
    expect(screen.getByText(DETAIL)).toBeInTheDocument()
    expect(screen.getByText(/Nothing was dispatched/)).toBeInTheDocument()
  })
})
