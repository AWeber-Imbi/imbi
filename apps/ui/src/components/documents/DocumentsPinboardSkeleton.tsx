import { Sk } from '@/components/ui/skeleton'

/**
 * Initial-load skeleton for {@link DocumentsTab}. The pinboard view gets a
 * footprint-matched skeleton; a `renderList` consumer (e.g. the org-wide
 * feed) gets a stacked-row feed skeleton.
 */
export function DocumentsTabSkeleton({ feed }: { feed?: boolean }) {
  if (feed) return <DocumentsFeedSkeleton />
  return <DocumentsPinboardSkeleton />
}

function DocumentsFeedSkeleton() {
  return (
    <div aria-busy className="space-y-3">
      {Array.from({ length: 6 }, (_, i) => (
        <div
          className="border-tertiary bg-primary flex flex-col gap-2 rounded-lg border p-4"
          key={i}
        >
          <Sk line w="45%" />
          <Sk line w="90%" />
          <div className="mt-1 flex items-center gap-2">
            <Sk circle h={16} w={16} />
            <Sk line w={120} />
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * Footprint-matched skeleton for {@link DocumentsPinboard}: the 220px
 * filter rail beside a column of hero cards and an index-table body.
 * Purely presentational.
 */
function DocumentsPinboardSkeleton() {
  return (
    <div aria-busy className="grid grid-cols-[220px_1fr] gap-5">
      <FilterRailSkeleton />
      <div>
        <section className="mb-6 grid grid-cols-2 gap-3.5">
          <HeroCardSkeleton />
          <HeroCardSkeleton />
        </section>
        <section>
          <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
            <div className="border-tertiary bg-secondary grid items-center gap-3.5 border-b px-3.5 py-2.5">
              <Sk line w={72} />
            </div>
            {Array.from({ length: 6 }, (_, i) => (
              <IndexRowSkeleton key={i} />
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

function FilterRailSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <Sk h={32} r={6} w="100%" />
      {Array.from({ length: 6 }, (_, i) => (
        <Sk key={i} line w={`${50 + ((i * 13) % 45)}%`} />
      ))}
    </div>
  )
}

function HeroCardSkeleton() {
  return (
    <div className="border-tertiary bg-primary flex flex-col gap-2.5 rounded-lg border p-4">
      <Sk line w="80%" />
      <Sk line w="100%" />
      <Sk line w="90%" />
      <Sk line w="60%" />
      <div className="mt-2 flex items-center gap-2">
        <Sk circle h={16} w={16} />
        <Sk line w={120} />
      </div>
    </div>
  )
}

function IndexRowSkeleton() {
  return (
    <div className="border-tertiary flex items-center gap-3.5 border-b px-3.5 py-3 last:border-b-0">
      <div className="min-w-0 flex-[1.6] space-y-1.5">
        <Sk line w="55%" />
        <Sk line w="80%" />
      </div>
      <div className="flex-1">
        <Sk h={18} r={9999} w={64} />
      </div>
      <Sk circle h={20} w={20} />
      <Sk line w={48} />
    </div>
  )
}
