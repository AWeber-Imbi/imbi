import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import { Select } from './Select'

const options = [
  { label: 'Value 1', value: 'foo' },
  { label: 'Value 2', value: 'bar' },
  { label: 'Value 3', value: 'baz' },
  { label: 'Value 4', value: 'qux' },
  { label: 'Value 5', value: 'corgie' }
]

describe('Select', () => {
  it('should render successfully with defaults', () => {
    render(
      <div data-testid="select">
        <Select name="test" options={options} />
      </div>
    )
    const select = screen.getByTestId('select').children[0]
    expect(select).toHaveClass('form-input')
    expect(select).not.toHaveClass('border-red-700')
    expect(select).not.toHaveAttribute('multiple')
    expect(select).not.toHaveAttribute('placeholder')
    expect(select).toHaveValue('')
    fireEvent.change(select, { target: { value: 'foo' } })
    expect(select).toHaveValue('foo')
    fireEvent.change(select, { target: { value: 'baz' } })
    expect(select).toHaveValue('baz')
  })

  it('should render successfully with values passed in', () => {
    render(
      <div data-testid="select">
        <Select
          autoFocus={true}
          name="test"
          options={options}
          placeholder="Select"
        />
      </div>
    )
    const select = screen.getByTestId('select').children[0]
    expect(document.activeElement).toEqual(select)
    expect(select).toHaveClass('form-input')
    expect(select).not.toHaveClass('border-red-700')
    expect(select).toHaveAttribute('placeholder', 'Select')
  })

  it('should show the error state', () => {
    render(
      <div data-testid="select">
        <Select hasError={true} options={options} name="test" />
      </div>
    )
    const select = screen.getByTestId('select').children[0]
    expect(select).toHaveClass('form-input')
    expect(select).toHaveClass('border-red-700')
  })

  it('should not show the error state when focused', () => {
    render(
      <div data-testid="select">
        <Select
          autoFocus={true}
          options={options}
          hasError={true}
          name="test"
        />
      </div>
    )
    const select = screen.getByTestId('select').children[0]
    expect(select).toHaveClass('form-input')
    expect(select).not.toHaveClass('border-red-700')
    select.blur()
    expect(select).toHaveClass('border-red-700')
  })

  it('should invoke callback on change', () => {
    const mockCallback = jest.fn()
    render(
      <div data-testid="select">
        <Select name="test" options={options} onChange={mockCallback} />
      </div>
    )
    const select = screen.getByTestId('select').children[0]
    fireEvent.change(select, { target: { value: 'bar' } })
    expect(select).toHaveValue('bar')
    expect(mockCallback.mock.calls.length).toBe(2)
    fireEvent.change(select, { target: { value: 'baz' } })
    expect(select).toHaveValue('baz')
    expect(mockCallback.mock.calls.length).toBe(3)
  })
})
