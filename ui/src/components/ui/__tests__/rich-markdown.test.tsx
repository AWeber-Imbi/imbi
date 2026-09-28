import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ProjectRepoProvider } from '@/contexts/ProjectRepoContext'
import { render } from '@/test/utils'

import { RichMarkdown } from '../rich-markdown'

const GH = 'https://github.com/aweber-imbi/imbi'

function renderWithRepo(markdown: string, repoUrl: null | string = GH) {
  return render(
    <ProjectRepoProvider repoUrl={repoUrl}>
      <RichMarkdown>{markdown}</RichMarkdown>
    </ProjectRepoProvider>,
  )
}

describe('RichMarkdown', () => {
  it('links #N references to the project repository', () => {
    renderWithRepo('- Fix the tabs cursor (#341)\n- See #12 and #7')
    expect(screen.getByRole('link', { name: '#341' })).toHaveAttribute(
      'href',
      `${GH}/issues/341`,
    )
    expect(screen.getByRole('link', { name: '#12' })).toHaveAttribute(
      'href',
      `${GH}/issues/12`,
    )
    expect(screen.getByRole('link', { name: '#7' })).toHaveAttribute(
      'target',
      '_blank',
    )
  })

  it('leaves references plain without a repository', () => {
    renderWithRepo('Fixes #12', null)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('Fixes #12')).toBeInTheDocument()
  })

  it('leaves references plain outside a project page', () => {
    render(<RichMarkdown>Fixes #12</RichMarkdown>)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('skips code, existing links, and mid-word hashes', () => {
    renderWithRepo(
      [
        'Inline `#1` code, [#2](https://example.com/two), sha#3, ##4.',
        '',
        '```',
        '#5',
        '```',
      ].join('\n'),
    )
    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', 'https://example.com/two')
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('#5')).toBeInTheDocument()
  })

  it('leaves URL fragments and reference links intact', () => {
    renderWithRepo(
      [
        'See https://example.com/page#123 and <https://example.com/x#45>',
        'and [#6][ref].',
        '',
        '[ref]: https://example.com/ref',
      ].join('\n'),
    )
    expect(
      screen.getAllByRole('link').map((a) => a.getAttribute('href')),
    ).toEqual([
      'https://example.com/page#123',
      'https://example.com/x#45',
      'https://example.com/ref',
    ])
  })
})
