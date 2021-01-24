import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import { TextArea } from './TextArea'

describe('TextArea', () => {
  it('should render successfully with defaults', () => {
    render(
      <div data-testid="textArea">
        <TextArea name="test" />
      </div>
    )
    const textArea = screen.getByTestId('textArea').children[0]
    expect(textArea).toHaveClass('form-input')
    expect(textArea).not.toHaveClass('border-red-700')
    expect(textArea).not.toHaveAttribute('placeholder')
    expect(textArea).toHaveValue('')
    fireEvent.blur(textArea, { target: { value: 'bar' } })
    expect(textArea).toHaveValue('bar')
    fireEvent.change(textArea, { target: { value: 'baz' } })
    expect(textArea).toHaveValue('baz')
  })

  it('should render successfully values passed in', () => {
    render(
      <div data-testid="textArea">
        <TextArea autoFocus={true} name="test" placeholder="foo" value="bar" />
      </div>
    )
    const textArea = screen.getByTestId('textArea').children[0]
    expect(document.activeElement).toEqual(textArea)
    expect(textArea).toHaveClass('form-input')
    expect(textArea).not.toHaveClass('border-red-700')
    expect(textArea).toHaveAttribute('placeholder', 'foo')
    expect(textArea).toHaveValue('bar')
  })

  it('should show the error state', () => {
    render(
      <div data-testid="textArea">
        <TextArea hasError={true} name="test" />
      </div>
    )
    const textArea = screen.getByTestId('textArea').children[0]
    expect(textArea).toHaveClass('form-input')
    expect(textArea).toHaveClass('border-red-700')
  })

  it('should not show the error state when focused', () => {
    render(
      <div data-testid="textArea">
        <TextArea autoFocus={true} hasError={true} name="test" />
      </div>
    )
    const textArea = screen.getByTestId('textArea').children[0]
    expect(textArea).toHaveClass('form-input')
    expect(textArea).not.toHaveClass('border-red-700')
  })

  it('should invoke callback on change', () => {
    const mockCallback = jest.fn()
    render(
      <div data-testid="textArea">
        <TextArea name="test" onChange={mockCallback} value="foo" />
      </div>
    )
    const textArea = screen.getByTestId('textArea').children[0]
    expect(textArea).toHaveValue('foo')
    fireEvent.blur(textArea, { target: { value: 'bar' } })
    expect(textArea).toHaveValue('bar')
    expect(mockCallback.mock.calls.length).toBe(1)
    fireEvent.change(textArea, { target: { value: 'baz' } })
    expect(textArea).toHaveValue('baz')
    expect(mockCallback.mock.calls.length).toBe(2)
  })
})
