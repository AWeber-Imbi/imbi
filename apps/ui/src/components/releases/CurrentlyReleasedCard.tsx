import { Clock, ExternalLink } from 'lucide-react'

import { UserIdentity } from '@/components/ui/user-identity'
import { formatRelativeDate } from '@/lib/formatDate'
import type { ReleaseHistoryEntry } from '@/types'

import type { ArtifactInfo } from './artifact'
import { CiStatusDot } from './CiStatusDot'

interface CurrentlyReleasedCardProps {
  artifact: ArtifactInfo
  released: null | ReleaseHistoryEntry
}

export function CurrentlyReleasedCard({
  artifact,
  released,
}: CurrentlyReleasedCardProps) {
  const ArtifactIcon = artifact.icon
  return (
    <div className="border-tertiary bg-primary rounded-lg border px-4 py-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="text-tertiary text-xs tracking-wider uppercase">
          Currently released
        </p>
        {artifact.indexUrl ? (
          <a
            className="text-tertiary hover:text-primary inline-flex items-center gap-1.5 text-xs"
            href={artifact.indexUrl}
            rel="noopener noreferrer"
            target="_blank"
          >
            <ArtifactIcon size={13} />
            {artifact.indexLabel ?? 'Package index'}
          </a>
        ) : null}
      </div>

      {released ? (
        <>
          <div className="flex items-baseline gap-2.5">
            <span className="font-mono text-xl font-semibold">
              {released.tag}
            </span>
            <span className="text-tertiary font-mono text-xs">
              {released.short_sha}
            </span>
            <CiStatusDot status={released.ci_status} />
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-4">
            <StatPill icon={Clock}>
              Published {formatRelativeDate(released.published_at)}
            </StatPill>
            {released.author ? (
              <UserIdentity
                actor={released.author}
                email={released.author_email}
                size="small"
              />
            ) : null}
            {artifact.pull ? (
              <StatPill icon={ArtifactIcon}>
                <span className="font-mono">{artifact.pull}</span>
              </StatPill>
            ) : null}
            {released.release_url ? (
              <a
                className="text-tertiary hover:text-primary inline-flex items-center gap-1 text-xs"
                href={released.release_url}
                rel="noopener noreferrer"
                target="_blank"
              >
                <ExternalLink size={12} />
                Release notes
              </a>
            ) : null}
          </div>
        </>
      ) : (
        <p className="text-tertiary text-sm">No releases published yet.</p>
      )}
    </div>
  )
}

function StatPill({
  children,
  icon: Icon,
}: {
  children: React.ReactNode
  icon: typeof Clock
}) {
  return (
    <span className="text-tertiary inline-flex items-center gap-1.5 text-xs">
      <Icon size={13} />
      {children}
    </span>
  )
}
