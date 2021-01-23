import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

const mockOnCancel = jest.fn()

import { Button } from './Button'

describe('Button', () => {
  it('should have defaults', () => {
    render(
      <div data-testid="btn">
        <Button>Default Button</Button>
      </div>
    )
    const button = screen.getByTestId('btn').children[0]
    expect(button).not.toHaveAttribute('disabled')
    expect(button).toHaveAttribute('type', 'button')
    expect(button).toHaveClass('btn-white')
    expect(button).toHaveTextContent('Default Button')
  })
  it('should render the button', () => {
    render(
      <div data-testid="btn">
        <Button className="btn-green" type="submit">
          Test Button
        </Button>
      </div>
    )

    const button = screen.getByTestId('btn').children[0]
    expect(button).not.toHaveAttribute('disabled')
    expect(button).toHaveClass('btn-green')
    expect(button).not.toHaveClass('btn-white')
    expect(button).toHaveTextContent('Test Button')
    expect(button).toHaveAttribute('type', 'submit')
  })
  it('should execute the onClick callback on click', () => {
    render(
      <div data-testid="btn">
        <Button onClick={mockOnCancel}>Save</Button>
      </div>
    )
    const button = screen.getByTestId('btn').children[0]
    expect(button).toHaveTextContent('Save')
    fireEvent.click(button)
    expect(mockOnCancel.mock.calls.length).toBe(1)
  })
  it('should behave like a disabled button', () => {
    render(
      <div data-testid="btn">
        <Button className="btn-red" disabled={true}>
          Cancel
        </Button>
      </div>
    )
    const button = screen.getByTestId('btn').children[0]
    expect(button).toHaveAttribute('disabled')
    expect(button).toHaveClass('btn-disabled')
    expect(button).not.toHaveClass('btn-red')
    expect(button).toHaveTextContent('Cancel')
  })
})
