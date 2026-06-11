import { Sk } from '@/components/ui/skeleton'

import { OPS_ROW_GRID, OPS_ROW_PAD } from './opsRowLayout'

/** A stack of `count` feed-row skeletons inside the bordered list shell. */
export function OperationsLogFeedSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="border-tertiary bg-primary w-full overflow-hidden rounded-md border">
      {Array.from({ length: count }, (_, i) => (
        <FeedRowSkeleton key={i} />
      ))}
    </div>
  )
}

/**
 * Footprint-matched skeleton for a single feed row. Mirrors the
 * `OperationsLogStreamRow` 9-column grid: rail · icon · project + desc ·
 * version · env chip · avatar · time. Purely presentational.
 */
function FeedRowSkeleton() {
  return (
    <div className="border-tertiary border-b last:border-b-0">
      <div
        className={`grid w-full items-center gap-x-3 gap-y-1 ${OPS_ROW_PAD}`}
        style={{
          gridTemplateColumns: OPS_ROW_GRID,
          gridTemplateRows: 'auto auto',
        }}
      >
        <span
          className="bg-tertiary self-stretch rounded-r-sm"
          style={{ gridColumn: 1, gridRow: '1 / -1' }}
        />
        <Sk h={26} r={6} style={{ gridColumn: 2, gridRow: 1 }} w={26} />
        <Sk line style={{ gridColumn: 3, gridRow: 1 }} w="70%" />
        <Sk line style={{ gridColumn: 4, gridRow: 1 }} w={44} />
        <span style={{ gridColumn: 6, gridRow: '1 / -1' }}>
          <Sk h={20} r={4} w={88} />
        </span>
        <span style={{ gridColumn: 7, gridRow: '1 / -1' }}>
          <Sk circle h={22} w={22} />
        </span>
        <Sk line style={{ gridColumn: 8, gridRow: '1 / -1' }} w={40} />
        <Sk line style={{ gridColumn: '3 / 6', gridRow: 2 }} w="55%" />
      </div>
    </div>
  )
}
