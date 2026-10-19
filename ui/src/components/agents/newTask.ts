import {
  Bug,
  GitPullRequest,
  Link as LinkIcon,
  type LucideIcon,
  MessageSquare,
} from 'lucide-react'

const TITLE_MAX = 96

interface Source {
  icon: LucideIcon
  label: string
  url: string
}

/** The first link of the request, and what it is. */
export function detectSource(text: string): null | Source {
  const url = text.match(/https?:\/\/\S+/)?.[0]
  if (!url) return null
  if (/sentry/i.test(url)) return { icon: Bug, label: 'Sentry issue', url }
  if (/\/pull\/\d+/.test(url))
    return { icon: GitPullRequest, label: 'Pull request', url }
  if (/slack\.com/i.test(url))
    return { icon: MessageSquare, label: 'Slack thread', url }
  return { icon: LinkIcon, label: 'Link', url }
}

/** The task title: the first line of the request without its links. */
export function titleFrom(text: string): string {
  const line =
    text
      .replace(/https?:\/\/\S+/g, '')
      .trim()
      .split('\n')[0]
      ?.trim() ?? ''
  const title =
    line || `Work from ${detectSource(text)?.label.toLowerCase() ?? 'link'}`
  return title.length > TITLE_MAX ? `${title.slice(0, TITLE_MAX - 1)}…` : title
}
