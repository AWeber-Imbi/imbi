import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceLine,
  TraceTitle,
} from '../trace'

describe('Trace', () => {
  it('opens a collapsible row when its trigger is clicked', async () => {
    render(
      <Trace>
        <TraceCollapsible>
          <TraceCollapsibleTrigger>
            <TraceLine>
              <TraceTitle>Ran ls</TraceTitle>
            </TraceLine>
          </TraceCollapsibleTrigger>
          <TraceCollapsibleContent>listing output</TraceCollapsibleContent>
        </TraceCollapsible>
      </Trace>,
    )

    expect(screen.queryByText('listing output')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Ran ls/ }))
    expect(screen.getByText('listing output')).toBeVisible()
  })
})
