import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { render } from '@/test/utils'

import { Textarea } from './textarea'

// jsdom has no layout, so scrollHeight is always 0. Stand in a value derived
// from the line count so the grow behaviour is observable.
const LINE_HEIGHT = 16
let original: PropertyDescriptor | undefined

beforeEach(() => {
  original = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    'scrollHeight',
  )
  Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      return this.value.split('\n').length * LINE_HEIGHT
    },
  })
})

afterEach(() => {
  if (original)
    Object.defineProperty(
      HTMLTextAreaElement.prototype,
      'scrollHeight',
      original,
    )
  else
    delete (HTMLTextAreaElement.prototype as Partial<HTMLTextAreaElement>)
      .scrollHeight
})

describe('Textarea autoResize', () => {
  it('sizes to a programmatically set value', () => {
    render(<Textarea autoResize value={'a\nb\nc\nd'} />)
    expect(screen.getByRole('textbox').style.height).toBe(
      `${4 * LINE_HEIGHT}px`,
    )
  })

  it('shrinks and regrows when the value changes', () => {
    const { rerender } = render(<Textarea autoResize value={'a\nb\nc'} />)
    expect(screen.getByRole('textbox').style.height).toBe(
      `${3 * LINE_HEIGHT}px`,
    )
    rerender(<Textarea autoResize value="a" />)
    expect(screen.getByRole('textbox').style.height).toBe(`${LINE_HEIGHT}px`)
    rerender(<Textarea autoResize value={'a\nb\nc'} />)
    expect(screen.getByRole('textbox').style.height).toBe(
      `${3 * LINE_HEIGHT}px`,
    )
  })

  it('grows as the user types', async () => {
    const user = userEvent.setup()
    render(<Textarea autoResize defaultValue="" />)
    const el = screen.getByRole('textbox')
    await user.type(el, 'one{enter}two{enter}three')
    expect(el.style.height).toBe(`${3 * LINE_HEIGHT}px`)
  })

  it('leaves the height alone without autoResize', () => {
    render(<Textarea value={'a\nb\nc\nd'} />)
    expect(screen.getByRole('textbox').style.height).toBe('')
  })
})
