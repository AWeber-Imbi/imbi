import { sanitizeHttpUrl } from './utils'

/**
 * A run of commit-subject text, optionally carrying the pull-request URL
 * a ``#N`` reference resolves to.
 */
export interface CommitSubjectSegment {
  /** Pull-request URL for a ``#N`` segment; null for plain text. */
  href: null | string
  text: string
}

// ``#123`` references, as the source host itself linkifies them. The
// lookbehind keeps mid-word noise (``sha#12``, ``##12``) from matching.
const PR_REF_RE = /(?<![\w#])#(\d+)\b/g

/**
 * The pull requests a commit subject references, deduplicated and in
 * message order. Used where the subject can't host inline links (e.g.
 * inside a clickable row) and the references need their own affordance.
 */
export function pullRequestRefs(
  subject: string,
  commitUrl: null | string | undefined,
): { href: string; label: string }[] {
  const repoUrl = repoWebUrl(commitUrl)
  if (!repoUrl) return []
  const seen = new Set<string>()
  const refs: { href: string; label: string }[] = []
  for (const match of subject.matchAll(PR_REF_RE)) {
    if (seen.has(match[1])) continue
    seen.add(match[1])
    refs.push({ href: `${repoUrl}/pull/${match[1]}`, label: match[0] })
  }
  return refs
}

/**
 * Repository web root behind a commit's ``html_url``
 * (``https://host/owner/repo/commit/<sha>`` → ``https://host/owner/repo``),
 * or null when the URL isn't a commit URL we recognize.
 *
 * The synced ClickHouse ``commits`` table carries no PR number, so the
 * commit URL is the only per-row handle on the repository the ``#N``
 * references in its message belong to.
 */
export function repoWebUrl(
  commitUrl: null | string | undefined,
): null | string {
  const sanitized = sanitizeHttpUrl(commitUrl)
  if (!sanitized) return null
  const { origin, pathname } = new URL(sanitized)
  const parts = pathname.split('/').filter(Boolean)
  // …/{owner}/{repo}/commit/{sha}
  if (parts.length < 4 || parts[parts.length - 2] !== 'commit') return null
  return `${origin}/${parts.slice(0, -2).join('/')}`
}

/**
 * Split a commit subject into plain-text and pull-request-reference
 * segments. Returns the subject as a single plain segment when there is
 * no repository to resolve references against.
 */
export function splitPullRequestRefs(
  subject: string,
  repoUrl: null | string,
): CommitSubjectSegment[] {
  if (!repoUrl) return [{ href: null, text: subject }]
  const segments: CommitSubjectSegment[] = []
  let cursor = 0
  for (const match of subject.matchAll(PR_REF_RE)) {
    const at = match.index
    if (at > cursor) {
      segments.push({ href: null, text: subject.slice(cursor, at) })
    }
    segments.push({ href: `${repoUrl}/pull/${match[1]}`, text: match[0] })
    cursor = at + match[0].length
  }
  if (cursor < subject.length) {
    segments.push({ href: null, text: subject.slice(cursor) })
  }
  return segments
}
