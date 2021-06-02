import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/extend-expect'

import { Field } from './Field'

describe('Field', () => {
  it('should render an IconSelect', () => {
    render(
      <div data-testid="field">
        <Field name="test" title="Field Text" type="icon" value="fas cube" />
      </div>
    )
    const label = screen.getByTestId('field').children[0].children[0]
    expect(label).toHaveTextContent('Field Text')
    const field = screen.getByTestId('field').children[0].children[1]
      .children[1]
    expect(field).toBeInstanceOf(HTMLSelectElement)
  })
  it('should render a NumericInput', () => {
    render(
      <div data-testid="field">
        <Field name="test" title="Number Test" type="number" value={10} />
      </div>
    )
    const label = screen.getByTestId('field').children[0].children[0]
    expect(label).toHaveTextContent('Number Test')
    const field = screen.getByTestId('field').children[0].children[1]
      .children[0]
    expect(field).toBeInstanceOf(HTMLInputElement)
    expect(field).toHaveValue(10)
  })

  it('should render a Select', () => {
    render(
      <div data-testid="field">
        <Field
          name="test"
          title="Select Test"
          options={[{ label: 'Foo', value: 'foo' }]}
          type="select"
        />
      </div>
    )
    const label = screen.getByTestId('field').children[0].children[0]
    expect(label).toHaveTextContent('Select Test')
    const field = screen.getByTestId('field').children[0].children[1]
      .children[0]
    expect(field).toBeInstanceOf(HTMLSelectElement)
  })

  it('should render a TextArea', () => {
    render(
      <div data-testid="field">
        <Field name="test" title="TextArea Test" type="textarea" value="foo" />
      </div>
    )
    const label = screen.getByTestId('field').children[0].children[0]
    expect(label).toHaveTextContent('TextArea Test')
    const field = screen.getByTestId('field').children[0].children[1]
      .children[0]
    expect(field).toBeInstanceOf(HTMLTextAreaElement)
    expect(field).toHaveValue('foo')
  })

  it('should render a TextInput', () => {
    render(
      <div data-testid="field">
        <Field name="test" title="Text Test" type="text" value="foo" />
      </div>
    )
    const label = screen.getByTestId('field').children[0].children[0]
    expect(label).toHaveTextContent('Text Test')
    const field = screen.getByTestId('field').children[0].children[1]
      .children[0]
    expect(field).toBeInstanceOf(HTMLInputElement)
    expect(field).toHaveValue('foo')
  })

  it('should render an error instead of a description', () => {
    render(
      <div data-testid="field">
        <Field
          name="test"
          title="Text Test"
          type="text"
          value="foo"
          errorMessage="oops"
          description="This is a test"
        />
      </div>
    )
    const label = screen.getByTestId('field').children[0].children[0]
    expect(label).toHaveTextContent('Text Test')
    const desc = screen.getByTestId('field').children[0].children[1].children[1]
    expect(desc).toBeInstanceOf(HTMLParagraphElement)
    expect(desc).toHaveTextContent('oops')
    expect(desc).toHaveClass('text-red-700')
    expect(desc).not.toHaveClass('text-gray-500')
  })
})
