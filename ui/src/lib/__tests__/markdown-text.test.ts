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

  it('keeps table cells and raw HTML as the literal text it shows', () => {
    expect(
      markdownText(
        '| a | b |\n| - | - |\n| c | d |\n\n<div>x</div>\n\nan <b>bold</b> tag',
      ),
    ).toBe('a\nb\nc\nd\n<div>x</div>\nan <b>bold</b> tag')
  })

  it('reads frontmatter as the table of keys and formatted values', () => {
    expect(
      markdownText(
        '---\nchecks:\n  - lint\n  - test\nowner: "**ops**"\n---\nThe body',
      ),
    ).toBe('checks\nlint, test\nowner\nops\nThe body')
  })

  it('reads a block that is not a YAML mapping as Markdown', () => {
    expect(markdownText('---\n- a\n---\nThe body')).toBe('\na\n\nThe body')
  })

  it('reads an image as the button that loads it', () => {
    expect(markdownText('![the chart](https://x.io/c.png)')).toBe(
      'Show image: the chart',
    )
  })
})
