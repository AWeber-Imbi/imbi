import { describe, expect, it } from 'vitest'

import { ProjectEnvironmentsCard } from '@/components/ProjectEnvironmentsCard'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { render, screen } from '@/test/utils'
import type { LatestDeployment, Project } from '@/types'

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

// The deployed release and the newest attempt are different facts, so
// the card shows both: the served version with its status badge, and a
// second badge for an attempt that has not replaced it.
describe('ProjectEnvironmentsCard latest deployment', () => {
  function renderCard(latest: LatestDeployment | null) {
    return render(
      <ThemeProvider>
        <ProjectEnvironmentsCard
          deploymentStatus={{
            prod: {
              committish: 'abc1234',
              latest,
              performedBy: null,
              performedByEmail: null,
              status: 'success',
              tag: '1.2.0',
              updated: '2 hours ago',
            },
          }}
          environments={[env('prod', null)]}
          orgSlug="acme"
          projectId="1"
        />
      </ThemeProvider>,
    )
  }

  it('shows a newer in-flight attempt beside the served release', () => {
    renderCard({
      committish: 'def5678',
      deployed_at: '2026-08-01T00:00:00Z',
      status: 'in_progress',
      tag: '1.3.0',
    })

    expect(screen.getByText('1.2.0')).toBeInTheDocument()
    expect(screen.getByText('Deployed')).toBeInTheDocument()
    expect(screen.getByText('1.3.0')).toBeInTheDocument()
    expect(screen.getByText('Deploying')).toBeInTheDocument()
  })

  it('shows only the served release when it is the newest attempt', () => {
    renderCard(null)

    expect(screen.getByText('1.2.0')).toBeInTheDocument()
    expect(screen.getByText('Deployed')).toBeInTheDocument()
    expect(screen.queryByText('Deploying')).not.toBeInTheDocument()
  })

  // An environment whose first-ever deployment is in flight (or failed)
  // has no serving release at all. It still has something to show, and
  // the projects list shows it -- the detail page rendered nothing.
  it('shows an attempt for an environment with nothing serving yet', () => {
    render(
      <ThemeProvider>
        <ProjectEnvironmentsCard
          deploymentStatus={{
            prod: {
              committish: null,
              latest: {
                committish: 'def5678',
                deployed_at: '2026-08-01T00:00:00Z',
                status: 'in_progress',
                tag: '1.3.0',
              },
              performedBy: null,
              performedByEmail: null,
              status: '',
              tag: null,
              updated: null,
            },
          }}
          environments={[env('prod', null)]}
          orgSlug="acme"
          projectId="1"
        />
      </ThemeProvider>,
    )

    expect(screen.getByText('1.3.0')).toBeInTheDocument()
    expect(screen.getByText('Deploying')).toBeInTheDocument()
    // Nothing is serving, so no release badge claims otherwise.
    expect(screen.queryByText('Deployed')).not.toBeInTheDocument()
  })
})
