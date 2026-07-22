import { Sk } from '@/components/ui/skeleton'

/** A stack of `count` result-card skeletons. */
export function SearchResultsSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div aria-hidden className="flex-1 overflow-hidden">
      {Array.from({ length: count }, (_, i) => (
        <ResultCardSkeleton key={i} />
      ))}
    </div>
  )
}

/**
 * Footprint-matched skeleton for a single search result row. Mirrors
 * `ResultCard`: entity badge · title + breadcrumb · snippet · confidence.
 * Purely presentational.
 */
function ResultCardSkeleton() {
  return (
    <div className="border-border flex w-full items-center gap-3 border-b px-4 py-2.5">
      <Sk h={20} r={4} w={64} />
      <div className="flex min-w-0 flex-[0_0_15%] flex-col gap-1.5">
        <Sk line w="80%" />
        <Sk line w="55%" />
      </div>
      <div className="min-w-0 flex-1">
        <Sk line w="70%" />
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <Sk line w={52} />
        <Sk h={2} r={9999} w={56} />
      </div>
    </div>
  )
}
