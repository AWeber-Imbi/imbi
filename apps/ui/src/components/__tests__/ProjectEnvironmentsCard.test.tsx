import { describe, expect, it } from 'vitest'

import { ProjectEnvironmentsCard } from '@/components/ProjectEnvironmentsCard'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { render, screen } from '@/test/utils'
import type { Project } from '@/types'

type Environment = NonNullable<Project['environments']>[number]

function env(slug: string, url: null | string): Environment {
  return {
    label_color: '#888888',
    name: slug,
    slug,
    url,
  } as unknown as Environment
}

// Covers the displayUrl/anchor rendering branches introduced by sanitizeUri:
// http(s) links are stripped for display and linkable, non-http URI schemes are
// shown verbatim and linkable, and blocked/invalid values are shown as-is with
// no anchor.
describe('ProjectEnvironmentsCard URL rendering', () => {
  function renderCard(environments: Environment[]) {
    return render(
      <ThemeProvider>
        <ProjectEnvironmentsCard
          deploymentStatus={{}}
          environments={environments}
          orgSlug="acme"
          projectId="1"
        />
      </ThemeProvider>,
    )
  }

  it('strips protocol and trailing slash for http(s) URLs and links them', () => {
    renderCard([env('prod', 'https://prod.example.com/')])

    expect(screen.getByText('prod.example.com')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Open URL' })
    expect(link).toHaveAttribute('href', 'https://prod.example.com/')
  })

  it('preserves non-http URI schemes verbatim, including a trailing slash', () => {
    renderCard([env('db', 'postgresql://db.example.cloud/prod/')])

    // Non-http schemes are shown as-is: the trailing slash is NOT stripped
    // (that shortening applies only to http(s) links).
    expect(
      screen.getByText('postgresql://db.example.cloud/prod/'),
    ).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Open URL' })
    expect(link).toHaveAttribute('href', 'postgresql://db.example.cloud/prod/')
  })

  it('shows blocked schemes as-is without an anchor', () => {
    renderCard([env('bad', 'javascript:alert(1)')])

    expect(screen.getByText('javascript:alert(1)')).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Open URL' }),
    ).not.toBeInTheDocument()
  })

  it('shows unparseable values as-is without an anchor', () => {
    renderCard([env('weird', 'not a url')])

    expect(screen.getByText('not a url')).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Open URL' }),
    ).not.toBeInTheDocument()
  })
})
