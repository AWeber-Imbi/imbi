import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'
import { GitBranch } from 'lucide-react'

import { getReleaseDrift, getReleaseHistory } from '@/api/releases'
import { Sk, SkText, Swap } from '@/components/ui/skeleton'
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

  if (driftError || historyError) {
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
        {drift?.head_sha ? (
          <span className="text-tertiary inline-flex items-center gap-1.5 text-xs">
            <GitBranch size={13} />
            build{' '}
            <span className="font-mono">{drift.head_sha.slice(0, 7)}</span>
          </span>
        ) : null}
      </div>

      <Swap ready={!!drift && !driftLoading} skeleton={<DriftCardSkeleton />}>
        {drift ? (
          <ReleaseReadyCard
            drift={drift}
            onCut={() => {}}
            orgSlug={orgSlug}
            projectId={project.id}
          />
        ) : null}
      </Swap>
      <Swap
        delay={50}
        ready={!historyLoading}
        skeleton={<ReleaseHistorySkeleton />}
      >
        <CurrentlyReleasedCard artifact={artifact} released={released} />
        <ReleaseHistory
          artifact={artifact}
          currentTag={released?.tag ?? null}
          releases={history}
        />
      </Swap>
    </div>
  )
}

/** Footprint skeleton for the release-ready / drift hero card. */
function DriftCardSkeleton() {
  return (
    <div className="border-tertiary flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-center justify-between gap-3">
        <Sk h={16} w="30%" />
        <Sk h={28} r={6} w={104} />
      </div>
      <SkText widths={['100%', '70%']} />
    </div>
  )
}

/** Footprint skeleton for the currently-released card + history rows. */
function ReleaseHistorySkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="border-tertiary flex flex-col gap-2 rounded-lg border p-4">
        <Sk h={14} w="25%" />
        <SkText widths={['80%', '55%']} />
      </div>
      <div className="border-tertiary mt-3 flex flex-col gap-2 border-t pt-3">
        <Sk className="mb-1" w={88} />
        {Array.from({ length: 4 }, (_, i) => (
          <div
            className="grid grid-cols-[16px_1fr_auto_auto] items-center gap-3"
            key={i}
          >
            <Sk circle h={14} w={14} />
            <Sk line w="40%" />
            <Sk line w={56} />
            <Sk h={20} r={4} w={48} />
          </div>
        ))}
      </div>
    </div>
  )
}
