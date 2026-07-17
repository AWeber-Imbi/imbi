import { describe, expect, it, vi } from 'vitest'

import { EditLinksCard } from '@/components/EditLinksCard'
import { render, screen } from '@/test/utils'
import type { LinkDefinition } from '@/types'

function linkDef(slug: string, name: string): LinkDefinition {
  return {
    icon: null,
    name,
    slug,
    url_template: null,
  } as unknown as LinkDefinition
}

describe('EditLinksCard integration-slug collision', () => {
  const linkDefs = [
    linkDef('documentation', 'Documentation'),
    linkDef('sonarqube', 'SonarQube'),
  ]

  it('hides a links key that belongs to a connected integration', () => {
    render(
      <EditLinksCard
        integrationSlugs={new Set(['sonarqube'])}
        linkDefs={linkDefs}
        links={{
          documentation: 'https://docs.example.com',
          sonarqube: 'https://sonar.example.com/dashboard',
        }}
        onPatch={vi.fn().mockResolvedValue(undefined)}
      />,
    )

    // The genuine project link still renders as an editable row.
    expect(screen.getByText('Documentation')).toBeInTheDocument()
    // The integration-owned key is not shown as an editable row, even though
    // it matches a link definition slug.
    expect(screen.queryByText('SonarQube')).not.toBeInTheDocument()
    // and its dashboard URL is not exposed for inline editing here.
    expect(
      screen.queryByDisplayValue('https://sonar.example.com/dashboard'),
    ).not.toBeInTheDocument()
  })

  it('still renders the row when no integration owns the slug', () => {
    render(
      <EditLinksCard
        integrationSlugs={new Set()}
        linkDefs={linkDefs}
        links={{ sonarqube: 'https://sonar.example.com/dashboard' }}
        onPatch={vi.fn().mockResolvedValue(undefined)}
      />,
    )

    expect(screen.getByText('SonarQube')).toBeInTheDocument()
  })
})
