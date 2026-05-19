import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  ChevronRight,
  GitMerge,
  GitPullRequest,
  GitPullRequestClosed,
} from 'lucide-react'

import {
  getMyIdentities,
  getOrgPullRequests,
  getProjects,
} from '@/api/endpoints'
import { Card } from '@/components/ui/card'
import { useOrganization } from '@/contexts/OrganizationContext'
import { relTime } from '@/lib/formatDate'
import type { IdentityConnectionResponse, Project, PullRequest } from '@/types'

const GITHUB_PR_PLUGIN_SLUG = 'github-enterprise-cloud'
const DISPLAY_COUNT = 5

// fallow-ignore-next-line complexity
export function MyPullRequestsWidget() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''

  const { data: identities, isLoading: identitiesLoading } = useQuery({
    queryFn: ({ signal }) => getMyIdentities(signal),
    queryKey: ['me-identities'],
    staleTime: 0,
  })

  const login = identities ? githubLogin(identities) : undefined
  const hasIdentity = !identitiesLoading && !!login
  const notConnected = !identitiesLoading && !login

  const { data: prsData, isLoading: prsLoading } = useQuery({
    enabled: hasIdentity && !!orgSlug,
    queryFn: ({ signal }) =>
      getOrgPullRequests(
        orgSlug,
        { author: login, limit: DISPLAY_COUNT },
        signal,
      ),
    queryKey: ['my-prs-list', orgSlug, login],
    staleTime: 60 * 1000,
  })

  const { data: openCountData } = useQuery({
    enabled: hasIdentity && !!orgSlug,
    queryFn: ({ signal }) =>
      getOrgPullRequests(
        orgSlug,
        { author: login, limit: 1, state: 'open' },
        signal,
      ),
    queryKey: ['my-prs', orgSlug, login, 'open'],
    staleTime: 60 * 1000,
  })

  const { data: projects } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })

  const projectsById = useMemo(() => {
    const m = new Map<string, Project>()
    for (const p of projects ?? []) m.set(p.id, p)
    return m
  }, [projects])

  const isLoading = identitiesLoading || prsLoading
  const prs = prsData?.data ?? []
  const total = openCountData?.total ?? 0

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <h3 className="text-primary text-lg font-semibold">
            My Pull Requests
          </h3>
          {!isLoading && total > 0 && (
            <span className="text-tertiary text-sm">
              {Math.min(DISPLAY_COUNT, prs.length)} of {total}
            </span>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              aria-hidden="true"
              className="bg-tertiary/30 h-20 animate-pulse rounded-lg"
              key={i}
            />
          ))}
        </div>
      ) : notConnected ? (
        <div className="text-secondary py-6 text-center text-sm">
          <p className="mb-2">No GitHub identity connected.</p>
          <a
            className="text-action text-xs hover:underline"
            href="/settings/connections"
          >
            Connect GitHub
          </a>
        </div>
      ) : prs.length === 0 ? (
        <div className="text-secondary py-6 text-center text-sm">
          No pull requests found.
        </div>
      ) : (
        <div className="space-y-2">
          {prs.map((pr) => (
            <PrRow key={pr.pr_id} pr={pr} projectsById={projectsById} />
          ))}
        </div>
      )}
    </Card>
  )
}

// fallow-ignore-next-line complexity
function githubLogin(
  identities: IdentityConnectionResponse[],
): string | undefined {
  const conn = identities.find((i) => i.plugin_slug === GITHUB_PR_PLUGIN_SLUG)
  if (!conn) return undefined
  const login = conn.metadata?.login
  return typeof login === 'string' && login ? login : undefined
}

// fallow-ignore-next-line complexity
function PrRow({
  pr,
  projectsById,
}: {
  pr: PullRequest
  projectsById: Map<string, Project>
}) {
  const project = projectsById.get(pr.project_id)
  const repoLabel = project ? `${project.team.slug}/${project.slug}` : undefined

  const { Icon, iconClass, stateClass, stateLabel } = prStateAttrs(pr)

  return (
    <a
      className="border-input bg-background hover:border-secondary flex w-full items-start gap-3 rounded-lg border p-3 transition-colors"
      href={pr.url}
      rel="noreferrer"
      target="_blank"
    >
      <Icon className={`mt-0.5 size-5 shrink-0 ${iconClass}`} />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-1.5">
          <span className="text-primary truncate font-medium">{pr.title}</span>
          <span className="text-tertiary shrink-0 text-xs">
            #{pr.pr_number}
          </span>
        </div>
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          {repoLabel && (
            <code className="bg-secondary text-primary rounded px-1.5 py-0.5 text-xs">
              {repoLabel}
            </code>
          )}
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${stateClass}`}
          >
            {stateLabel}
          </span>
          {(pr.additions > 0 || pr.deletions > 0) && (
            <>
              <span className="text-success text-xs">
                +{pr.additions.toLocaleString()}
              </span>
              <span className="text-danger text-xs">
                -{pr.deletions.toLocaleString()}
              </span>
            </>
          )}
        </div>
        <div className="text-tertiary text-xs">
          {relTime(pr.updated_at)} ago
        </div>
      </div>
      <ChevronRight className="text-tertiary mt-0.5 size-4 shrink-0" />
    </a>
  )
}

function prStateAttrs(pr: PullRequest) {
  if (pr.draft) {
    return {
      Icon: GitPullRequest,
      iconClass: 'text-tertiary',
      stateClass: 'bg-secondary text-secondary',
      stateLabel: 'Draft',
    }
  }
  if (pr.merged) {
    return {
      Icon: GitMerge,
      iconClass: 'text-purple-500',
      stateClass:
        'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
      stateLabel: 'Merged',
    }
  }
  if (pr.state === 'closed') {
    return {
      Icon: GitPullRequestClosed,
      iconClass: 'text-danger',
      stateClass: 'bg-danger/10 text-danger',
      stateLabel: 'Closed',
    }
  }
  return {
    Icon: GitPullRequest,
    iconClass: 'text-info',
    stateClass: 'bg-info/10 text-info',
    stateLabel: 'Open',
  }
}
