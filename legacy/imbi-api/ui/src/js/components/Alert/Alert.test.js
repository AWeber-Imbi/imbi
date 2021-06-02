import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import '../../icons'
import { Alert } from './Alert'

describe('Alert', () => {
  it('should render an alert with info attributes', () => {
    render(
      <div data-testid="alert">
        <Alert level="info">Alert Info Content</Alert>
      </div>
    )
    const alert = screen.getByTestId('alert').children[0]
    expect(alert).toHaveClass('bg-blue-50')
    const svg = alert.getElementsByTagName('svg')[0]
    expect(svg.dataset.prefix).toBe('fas')
    expect(svg.dataset.icon).toBe('info-circle')
    const h3 = alert.getElementsByTagName('h3')[0]
    expect(h3).toHaveTextContent('Alert Info Content')
  })
  it('should render an alert with warning attributes', () => {
    render(
      <div data-testid="alert">
        <Alert level="warning">Alert Warning Content</Alert>
      </div>
    )
    const alert = screen.getByTestId('alert').children[0]
    expect(alert).toHaveClass('bg-yellow-50')
    const svg = alert.getElementsByTagName('svg')[0]
    expect(svg.dataset.prefix).toBe('fas')
    expect(svg.dataset.icon).toBe('exclamation-triangle')
    const h3 = alert.getElementsByTagName('h3')[0]
    expect(h3).toHaveTextContent('Alert Warning Content')
  })
  it('should render children even if they are element', () => {
    render(
      <div data-testid="alert">
        <Alert level="success">
          <h1>Foo Bar</h1>
        </Alert>
      </div>
    )
    const alert = screen.getByTestId('alert').children[0]
    expect(alert).toHaveClass('bg-green-50')
    const svg = alert.getElementsByTagName('svg')[0]
    expect(svg.dataset.prefix).toBe('fas')
    expect(svg.dataset.icon).toBe('check-circle')
    const child = alert.getElementsByTagName('h1')[0]
    expect(child).toHaveTextContent('Foo Bar')
  })
})
