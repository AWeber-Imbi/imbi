import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import { TextInput } from './TextInput'

describe('TextInput', () => {
  it('should render successfully with defaults', () => {
    render(
      <div data-testid="input">
        <TextInput name="test" />
      </div>
    )
    const input = screen.getByTestId('input').children[0]
    expect(input).toHaveClass('form-input')
    expect(input).not.toHaveClass('border-red-700')
    expect(input).not.toHaveAttribute('placeholder')
    expect(input).toHaveValue('')
  })

  it('should render successfully values passed in', () => {
    render(
      <div data-testid="input">
        <TextInput autoFocus={true} name="test" placeholder="foo" value="bar" />
      </div>
    )
    const input = screen.getByTestId('input').children[0]
    expect(document.activeElement).toEqual(input)
    expect(input).toHaveClass('form-input')
    expect(input).not.toHaveClass('border-red-700')
    expect(input).toHaveAttribute('placeholder', 'foo')
    expect(input).toHaveValue('bar')
  })

  it('should show the error state', () => {
    render(
      <div data-testid="input">
        <TextInput hasError={true} name="test" />
      </div>
    )
    const input = screen.getByTestId('input').children[0]
    expect(input).toHaveClass('form-input')
    expect(input).toHaveClass('border-red-700')
  })

  it('should not show the error state when focused', () => {
    render(
      <div data-testid="input">
        <TextInput autoFocus={true} hasError={true} name="test" />
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
        <TextInput name="test" onChange={mockCallback} value="foo" />
      </div>
    )
    const input = screen.getByTestId('input').children[0]
    expect(input).toHaveValue('foo')
    fireEvent.blur(input, { target: { value: 'bar' } })
    expect(mockCallback.mock.calls.length).toBe(1)
    expect(mockCallback).toHaveBeenCalledWith('test', 'bar')
    fireEvent.change(input, { target: { value: 'baz' } })
    expect(mockCallback.mock.calls.length).toBe(2)
    expect(mockCallback).toHaveBeenCalledWith('test', 'baz')
  })
})
