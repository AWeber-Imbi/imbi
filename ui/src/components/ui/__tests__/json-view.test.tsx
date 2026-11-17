import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { JsonView } from '../json-view'

describe('JsonView', () => {
  it('renders keys and values the way JSON writes them', () => {
    const { container } = render(
      <JsonView data={{ command: 'ls', count: 2, none: null, ok: true }} />,
    )
    expect(container).toHaveTextContent('"command": "ls",')
    expect(container).toHaveTextContent('"count": 2,')
    expect(container).toHaveTextContent('"none": null,')
    expect(container).toHaveTextContent('"ok": true}')
  })

  it('folds a branch to a preview of its keys and opens it again', async () => {
    const { container } = render(
      <JsonView data={{ args: { a: 1, b: 2 }, list: [1, 2, 3] }} />,
    )
    const [, args, list] = screen.getAllByRole('button', { expanded: true })
    await userEvent.click(args)
    expect(args).toHaveAttribute('aria-expanded', 'false')
    expect(args).toHaveTextContent('"args": {a, b},')
    expect(container).not.toHaveTextContent('"a": 1')
    await userEvent.click(list)
    expect(list).toHaveTextContent('"list": [3 items]')
    await userEvent.click(args)
    expect(container).toHaveTextContent('"a": 1')
  })

  it('starts folded below the initial depth', () => {
    render(<JsonView data={{ deep: { x: 1 } }} initialDepth={1} />)
    expect(screen.getByRole('button', { expanded: false })).toHaveTextContent(
      '"deep": {x}',
    )
  })

  it('shows empty objects and arrays inline', () => {
    const { container } = render(<JsonView data={{ a: {}, b: [] }} />)
    expect(container).toHaveTextContent('"a": {},')
    expect(container).toHaveTextContent('"b": []')
    expect(screen.getAllByRole('button', { expanded: true })).toHaveLength(1)
  })

  it('folds a long string and shows all of it on request', async () => {
    const text = Array.from({ length: 20 }, (_, i) => `line ${i}`).join('\n')
    const { container } = render(<JsonView data={{ text }} stringLines={3} />)
    expect(container).toHaveTextContent('line 2…')
    expect(container).not.toHaveTextContent('line 3')
    await userEvent.click(
      screen.getByRole('button', { name: 'Show all 20 lines' }),
    )
    expect(container).toHaveTextContent('line 19')
    expect(
      screen.getByRole('button', { name: 'Show less' }),
    ).toBeInTheDocument()
  })

  it('folds one long line at the character budget', () => {
    const { container } = render(
      <JsonView data={'x'.repeat(500)} stringLines={2} />,
    )
    expect(container).toHaveTextContent(`"${'x'.repeat(240)}…"`)
    expect(
      screen.getByRole('button', { name: 'Show all 500 characters' }),
    ).toBeInTheDocument()
  })

  it('keeps a string that fits whole', () => {
    render(<JsonView data={'a\nb'} stringLines={2} />)
    expect(screen.queryByRole('button', { name: /Show all/ })).toBeNull()
  })

  it('shows a long array a page at a time', async () => {
    const { container } = render(
      <JsonView
        data={Array.from({ length: 250 }, (_, i) => i)}
        pageSize={100}
      />,
    )
    expect(container).toHaveTextContent('99,')
    expect(container).not.toHaveTextContent('100,')
    await userEvent.click(
      screen.getByRole('button', { name: 'Show 100 more of 150' }),
    )
    expect(container).toHaveTextContent('199,')
    await userEvent.click(
      screen.getByRole('button', { name: 'Show 50 more of 50' }),
    )
    expect(container).toHaveTextContent('249]')
    expect(screen.queryByRole('button', { name: /more of/ })).toBeNull()
  })

  it('copies the value of a line', async () => {
    const user = userEvent.setup()
    render(<JsonView data={{ command: 'ls' }} />)
    const [root, line] = screen.getAllByRole('button', { name: 'Copy' })
    await user.click(line)
    expect(await navigator.clipboard.readText()).toBe('ls')
    await user.click(root)
    expect(await navigator.clipboard.readText()).toBe('{\n  "command": "ls"\n}')
  })
})
