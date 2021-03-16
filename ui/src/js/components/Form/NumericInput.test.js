import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import { NumericInput } from './NumericInput'

describe('NumericInput', () => {
  it('should render successfully with defaults', () => {
    render(
      <div data-testid="input">
        <NumericInput name="test" />
      </div>
    )
    const input = screen.getByTestId('input').children[0]
    expect(input).toHaveClass('form-input')
    expect(input).not.toHaveClass('border-red-700')
    expect(input).not.toHaveAttribute('defaultValue')
    expect(input).not.toHaveAttribute('placeholder')
    expect(input).toHaveValue(null)
  })

  it('should render successfully values passed in', () => {
    render(
      <div data-testid="input">
        <NumericInput
          autoFocus={true}
          name="test"
          placeholder="number"
          value={200}
        />
      </div>
    )
    const input = screen.getByTestId('input').children[0]
    expect(document.activeElement).toEqual(input)
    expect(input).toHaveClass('form-input')
    expect(input).not.toHaveClass('border-red-700')
    expect(input).toHaveAttribute('placeholder', 'number')
    expect(input).toHaveValue(200)
  })

  it('should show the error state', () => {
    render(
      <div data-testid="input">
        <NumericInput hasError={true} name="test" />
      </div>
    )
    const input = screen.getByTestId('input').children[0]
    expect(input).toHaveClass('form-input')
    expect(input).toHaveClass('border-red-700')
  })

  it('should not show the error state when focused', () => {
    render(
      <div data-testid="input">
        <NumericInput autoFocus={true} hasError={true} name="test" />
      </div>
    )
    const input = screen.getByTestId('input').children[0]
    expect(input).toHaveClass('form-input')
    expect(input).not.toHaveClass('border-red-700')
  })

  it('should invoke callback on change', () => {
    const mockCallback = jest.fn()
    render(
      <div data-testid="input">
        <NumericInput name="test" onChange={mockCallback} value={100} />
      </div>
    )
    const input = screen.getByTestId('input').children[0]
    expect(input).toHaveValue(100)
    fireEvent.blur(input, { target: { value: '200' } })
    expect(mockCallback.mock.calls.length).toBe(1)
    expect(mockCallback).toHaveBeenCalledWith('test', 200)
    fireEvent.change(input, { target: { value: '300' } })
    expect(mockCallback.mock.calls.length).toBe(2)
    expect(mockCallback).toHaveBeenCalledWith('test', 300)
    fireEvent.change(input, { target: { value: '' } })
    expect(mockCallback.mock.calls.length).toBe(3)
    expect(mockCallback).toHaveBeenCalledWith('test', null)
    fireEvent.blur(input, { target: { value: '200' } })
    expect(mockCallback.mock.calls.length).toBe(4)
    expect(mockCallback).toHaveBeenCalledWith('test', 200)
    fireEvent.blur(input, { target: { value: '' } })
    expect(mockCallback.mock.calls.length).toBe(5)
    expect(mockCallback).toHaveBeenCalledWith('test', null)
  })
})
