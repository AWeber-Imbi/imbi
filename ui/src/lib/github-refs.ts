import type { Link, Root } from 'mdast'
import { findAndReplace } from 'mdast-util-find-and-replace'

import type { Integration, Project } from '@/types'

import { PR_REF_RE } from './commit-refs'
import { sanitizeHttpUrl } from './utils'

// Link key the GitHub plugin falls back to when a project isn't wired to
// an Integration (see the plugin's ``_record_repo``).
const LEGACY_REPO_LINK_KEY = 'github-repository'

interface RemarkGithubRefsOptions {
  /** Repository web root the ``#N`` references resolve against. */
  repoUrl?: null | string
}

/**
 * The GitHub web root (``https://host/owner/repo``) for a project, or null
 * when it has no GitHub repository Imbi knows about.
 *
 * Prefers the dashboard URL on a ``github``-plugin service edge -- the
 * repo's ``html_url``, kept current across renames and transfers -- and
 * falls back to the legacy ``github-repository`` project link.
 */
export function projectRepoUrl(
  project: Pick<Project, 'links' | 'services'>,
  integrations: Pick<Integration, 'plugin' | 'slug'>[],
): null | string {
  const githubSlugs = new Set(
    integrations.filter((i) => i.plugin === 'github').map((i) => i.slug),
  )
  for (const svc of project.services ?? []) {
    if (!githubSlugs.has(svc.integration_slug)) continue
    const url = repoRootUrl(svc.dashboard_url)
    if (url) return url
  }
  return repoRootUrl(project.links?.[LEGACY_REPO_LINK_KEY])
}

/**
 * Remark plugin that links bare ``#N`` references to the repository's
 * issue/PR page, the way GitHub renders them. ``/issues/N`` is used
 * because a bare reference can be either; GitHub redirects it to
 * ``/pull/N`` when N is a pull request.
 *
 * Only text nodes are rewritten, so inline code and fenced code are left
 * alone, and text already inside a link is skipped. A no-op without a
 * ``repoUrl``.
 */
export function remarkGithubRefs({ repoUrl }: RemarkGithubRefsOptions = {}) {
  return (tree: Root) => {
    if (!repoUrl) return
    findAndReplace(
      tree,
      [
        PR_REF_RE,
        (value: string, number: string): Link => ({
          children: [{ type: 'text', value }],
          type: 'link',
          url: `${repoUrl}/issues/${number}`,
        }),
      ],
      { ignore: ['link', 'linkReference'] },
    )
  }
}

/**
 * ``https://host/owner/repo`` from a repository URL, tolerating a
 * trailing slash or ``.git`` suffix; null for anything that isn't an
 * http(s) URL with at least an owner and repo path segment.
 */
function repoRootUrl(raw: null | string | undefined): null | string {
  const sanitized = sanitizeHttpUrl(raw)
  if (!sanitized) return null
  const { origin, pathname } = new URL(sanitized)
  const [owner, repo] = pathname.split('/').filter(Boolean)
  if (!owner || !repo) return null
  return `${origin}/${owner}/${repo.replace(/\.git$/, '')}`
}
