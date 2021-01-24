import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import { IconSelect } from './IconSelect'

describe('IconSelect', () => {
  it('should render successfully with defaults', () => {
    render(
      <div data-testid="select">
        <IconSelect name="test" value="fas cube" />
      </div>
    )
    const select = screen.getByTestId('select').children[1]
    expect(select).toHaveClass('form-input')
    expect(select).not.toHaveClass('border-red-700')
    expect(select).not.toHaveAttribute('placeholder')
    expect(select).toHaveValue('fas cube')
    fireEvent.change(select, { target: { value: 'fas cubes' } })
    expect(select).toHaveValue('fas cubes')
    fireEvent.change(select, { target: { value: 'imbi rabbitmq' } })
    expect(select).toHaveValue('imbi rabbitmq')
  })

  it('should render successfully values passed in', () => {
    render(
      <div data-testid="select">
        <IconSelect
          autoFocus={true}
          name="test"
          placeholder="Select"
          value="fas cubes"
        />
      </div>
    )
    const select = screen.getByTestId('select').children[1]
    expect(document.activeElement).toEqual(select)
    expect(select).toHaveClass('form-input')
    expect(select).not.toHaveClass('border-red-700')
    expect(select).toHaveAttribute('placeholder', 'Select')
    expect(select).toHaveValue('fas cubes')
  })

  it('should show the error state', () => {
    render(
      <div data-testid="select">
        <IconSelect hasError={true} name="test" value="fas cube" />
      </div>
    )
    const select = screen.getByTestId('select').children[1]
    expect(select).toHaveClass('form-input')
    expect(select).toHaveClass('border-red-700')
  })

  it('should not show the error state when focused', () => {
    render(
      <div data-testid="select">
        <IconSelect
          autoFocus={true}
          hasError={true}
          name="test"
          value="fas cube"
        />
      </div>
    )
    const select = screen.getByTestId('select').children[1]
    expect(select).toHaveClass('form-input')
    expect(select).not.toHaveClass('border-red-700')
    select.blur()
    expect(select).toHaveClass('border-red-700')
  })

  it('should invoke callback on change', () => {
    const mockCallback = jest.fn()
    render(
      <div data-testid="select">
        <IconSelect name="test" onChange={mockCallback} value="fas cube" />
      </div>
    )
    const select = screen.getByTestId('select').children[1]
    expect(select).toHaveValue('fas cube')
    fireEvent.change(select, { target: { value: 'fas cubes' } })
    expect(select).toHaveValue('fas cubes')
    expect(mockCallback.mock.calls.length).toBe(1)
    fireEvent.change(select, { target: { value: 'imbi rabbitmq' } })
    expect(select).toHaveValue('imbi rabbitmq')
    expect(mockCallback.mock.calls.length).toBe(2)
  })
})
