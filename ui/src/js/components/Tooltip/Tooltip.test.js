import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom/extend-expect'

import { Tooltip } from './Tooltip'

describe('Tooltip', () => {
  it('should change the visibility on mouse over/out', () => {
    render(
      <div data-testid="trigger">
        <Tooltip value="Tooltip">
          <div id="child">Foo</div>
        </Tooltip>
      </div>
    )
    const tooltip = screen.getByRole('tooltip')
    const trigger = screen.getByTestId('trigger').getElementsByTagName('div')[0]
    expect(tooltip).toHaveClass('hidden')
    expect(tooltip).not.toHaveClass('visible')
    userEvent.hover(trigger)
    expect(tooltip).not.toHaveClass('hidden')
    expect(tooltip).toHaveClass('visible')
    userEvent.unhover(trigger)
    expect(tooltip).toHaveClass('hidden')
    expect(tooltip).not.toHaveClass('visible')
  })
})
