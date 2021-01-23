import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import '../../icons'
import { Icon } from './Icon'

describe('Icon', () => {
  it('should render the check icon', () => {
    render(
      <div data-testid="icon">
        <Icon icon="fas check" />
      </div>
    )
    const child = screen.getByTestId('icon').children[0]
    expect(child.dataset.prefix).toBe('fas')
    expect(child.dataset.icon).toBe('check')
  })
})
