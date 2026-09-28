import { describe, expect, it } from 'vitest'

import { projectRepoUrl } from '../github-refs'

const GH = 'https://github.com/aweber-imbi/imbi'
const GHE = 'https://aweber.ghe.com/apis/address-verification'

const INTEGRATIONS = [
  { plugin: 'github', slug: 'github-com' },
  { plugin: 'github', slug: 'ghec' },
  { plugin: 'sonarqube', slug: 'sonar' },
]

function edge(integration_slug: string, dashboard_url: null | string) {
  return {
    dashboard_url,
    identifier: '1',
    integration_name: integration_slug,
    integration_slug,
  }
}

describe('projectRepoUrl', () => {
  it('uses the dashboard URL of a github-plugin service edge', () => {
    expect(
      projectRepoUrl({ services: [edge('ghec', GHE)] }, INTEGRATIONS),
    ).toBe(GHE)
  })

  it('ignores edges from other plugins', () => {
    expect(
      projectRepoUrl(
        {
          services: [
            edge('sonar', 'https://sonar.example.com/dashboard'),
            edge('github-com', GH),
          ],
        },
        INTEGRATIONS,
      ),
    ).toBe(GH)
  })

  it('falls back to the legacy github-repository link', () => {
    expect(
      projectRepoUrl(
        { links: { 'github-repository': `${GH}.git` }, services: [] },
        INTEGRATIONS,
      ),
    ).toBe(GH)
  })

  it('prefers the service edge over the legacy link', () => {
    expect(
      projectRepoUrl(
        {
          links: { 'github-repository': 'https://github.com/old/name' },
          services: [edge('github-com', GH)],
        },
        INTEGRATIONS,
      ),
    ).toBe(GH)
  })

  it('normalizes deeper and trailing-slash repo URLs to the repo root', () => {
    expect(
      projectRepoUrl(
        { services: [edge('github-com', `${GH}/`)] },
        INTEGRATIONS,
      ),
    ).toBe(GH)
    expect(
      projectRepoUrl(
        { services: [edge('github-com', `${GH}/tree/main`)] },
        INTEGRATIONS,
      ),
    ).toBe(GH)
  })

  it('returns null without a usable repository URL', () => {
    expect(projectRepoUrl({}, INTEGRATIONS)).toBeNull()
    expect(
      projectRepoUrl({ services: [edge('github-com', null)] }, INTEGRATIONS),
    ).toBeNull()
    expect(
      projectRepoUrl(
        { links: { 'github-repository': 'javascript:alert(1)' } },
        INTEGRATIONS,
      ),
    ).toBeNull()
    expect(
      projectRepoUrl(
        { links: { 'github-repository': 'https://github.com/owner-only' } },
        INTEGRATIONS,
      ),
    ).toBeNull()
  })
})
