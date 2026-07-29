import { Fragment } from 'react'

import { repoWebUrl, splitPullRequestRefs } from '@/lib/commit-refs'

interface CommitSubjectProps {
  className?: string
  /**
   * The commit's web URL. The repository behind it anchors the ``#N``
   * links; without it the subject renders as plain text.
   */
  commitUrl?: null | string
  /** Full commit message — only the subject line renders. */
  message: string
}

/**
 * A commit's subject line with its ``#N`` pull-request references linked,
 * matching how the same references render in the release notes below.
 */
export function CommitSubject({
  className,
  commitUrl,
  message,
}: CommitSubjectProps) {
  const subject = message.split('\n')[0] ?? ''
  const segments = splitPullRequestRefs(subject, repoWebUrl(commitUrl))
  return (
    <span className={className}>
      {segments.map((segment, idx) =>
        segment.href ? (
          <a
            className="text-warning hover:underline"
            href={segment.href}
            key={idx}
            rel="noopener noreferrer"
            target="_blank"
          >
            {segment.text}
          </a>
        ) : (
          <Fragment key={idx}>{segment.text}</Fragment>
        ),
      )}
    </span>
  )
}
