import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'
import { GitBranch } from 'lucide-react'

import { getReleaseDrift, getReleaseHistory } from '@/api/releases'
import { LoadingState } from '@/components/ui/loading-state'
import type { Project } from '@/types'

import { deriveArtifact } from './artifact'
import { CurrentlyReleasedCard } from './CurrentlyReleasedCard'
import { ReleaseHistory } from './ReleaseHistory'
import { ReleaseReadyCard } from './ReleaseReadyCard'

interface ReleasesTabProps {
  orgSlug: string
  project: Pick<Project, 'id' | 'links' | 'name'>
}

// fallow-ignore-next-line complexity
export function ReleasesTab({ orgSlug, project }: ReleasesTabProps) {
  const enabled = !!orgSlug && !!project.id
  const {
    data: drift,
    error: driftError,
    isLoading: driftLoading,
  } = useQuery({
    enabled,
    queryFn: ({ signal }) => getReleaseDrift(orgSlug, project.id, signal),
    queryKey: ['releaseDrift', orgSlug, project.id],
  })
  const {
    data: history = [],
    error: historyError,
    isLoading: historyLoading,
  } = useQuery({
    enabled,
    queryFn: ({ signal }) => getReleaseHistory(orgSlug, project.id, signal),
    queryKey: ['releaseHistory', orgSlug, project.id],
  })

  const artifact = useMemo(() => deriveArtifact(project), [project])
  const ArtifactIcon = artifact.icon

  if (driftLoading || historyLoading) {
    return <LoadingState label="Loading releases…" />
  }
  if (driftError || historyError || !drift) {
    return (
      <div className="border-tertiary text-tertiary rounded-lg border p-6 text-center text-sm">
        Could not load release data for this project.
      </div>
    )
  }

  const released = history[0] ?? null
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="inline-flex items-center gap-2 text-base font-semibold">
          <ArtifactIcon className="text-tertiary size-4" />
          Releases
        </h2>
        {drift.head_sha ? (
          <span className="text-tertiary inline-flex items-center gap-1.5 text-xs">
            <GitBranch size={13} />
            build{' '}
            <span className="font-mono">{drift.head_sha.slice(0, 7)}</span>
          </span>
        ) : null}
      </div>

      <ReleaseReadyCard
        drift={drift}
        onCut={() => {}}
        orgSlug={orgSlug}
        projectId={project.id}
      />
      <CurrentlyReleasedCard artifact={artifact} released={released} />
      <ReleaseHistory
        artifact={artifact}
        currentTag={released?.tag ?? null}
        releases={history}
      />
    </div>
  )
}
