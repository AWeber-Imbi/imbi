import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { render } from '@/test/utils'

import { FrontmatterTable } from '../frontmatter-table'

describe('FrontmatterTable', () => {
  it('renders cell values as markdown', () => {
    render(
      <FrontmatterTable
        meta={{
          Environment: 'infrastructure (`imbi.aweber.io`)',
          Upstream:
            '[apache/iggy#4273](https://github.com/apache/iggy/issues/4273)',
        }}
      />,
    )
    const link = screen.getByRole('link', { name: 'apache/iggy#4273' })
    expect(link).toHaveAttribute(
      'href',
      'https://github.com/apache/iggy/issues/4273',
    )
    expect(link).toHaveAttribute('target', '_blank')
    expect(screen.getByText('imbi.aweber.io').tagName).toBe('CODE')
  })
})
