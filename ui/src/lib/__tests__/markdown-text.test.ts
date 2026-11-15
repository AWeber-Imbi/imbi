import { describe, expect, it } from 'vitest'

import { markdownText } from '../markdown-text'

describe('markdownText', () => {
  it('drops inline syntax the rendered text does not show', () => {
    expect(
      markdownText(
        'Hi, *Pluto*! **Bold** `code` ~~gone~~ [link](https://x.io)',
      ),
    ).toBe('Hi, Pluto! Bold code gone link')
  })

  it('puts each block on its own line', () => {
    expect(
      markdownText('# Title\n\n> quoted\n\n- one\n- two\n\n```\nfenced\n```'),
    ).toBe('Title\nquoted\none\ntwo\nfenced')
  })

  it('keeps table cells and drops raw HTML', () => {
    expect(
      markdownText('| a | b |\n| - | - |\n| c | d |\n\n<div>x</div>'),
    ).toBe('a\nb\nc\nd\n')
  })

  it('reads an image as the button that loads it', () => {
    expect(markdownText('![the chart](https://x.io/c.png)')).toBe(
      'Show image: the chart',
    )
  })
})
