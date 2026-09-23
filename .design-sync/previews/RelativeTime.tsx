import { RelativeTime } from 'imbi-ui'

// Dates are offsets from now, so the card reads the same in capture
// (frozen clock) and in the live product.
const ago = (seconds: number) =>
  new Date(Date.now() - seconds * 1000).toISOString()

const DEPLOYED_AT = ago(354600)

export const Default = () => (
  <RelativeTime className="text-secondary text-sm" value={DEPLOYED_AT} />
)

export const Variants = () => (
  <div className="flex w-64 flex-col gap-2 text-sm">
    <div className="flex items-center justify-between gap-6">
      <span className="text-tertiary">narrow</span>
      <RelativeTime className="text-primary" value={DEPLOYED_AT} variant="narrow" />
    </div>
    <div className="flex items-center justify-between gap-6">
      <span className="text-tertiary">short</span>
      <RelativeTime className="text-primary" value={DEPLOYED_AT} variant="short" />
    </div>
    <div className="flex items-center justify-between gap-6">
      <span className="text-tertiary">long</span>
      <RelativeTime className="text-primary" value={DEPLOYED_AT} variant="long" />
    </div>
  </div>
)

export const Ranges = () => (
  <div className="flex w-64 flex-col gap-2 text-sm">
    {[
      ['Health check', ago(20)],
      ['Last deploy', ago(2520)],
      ['Latest tag', ago(71700)],
      ['Head commit', ago(1821600)],
      ['Created', ago(69544800)],
    ].map(([label, value]) => (
      <div className="flex items-center justify-between gap-6" key={label}>
        <span className="text-secondary">{label}</span>
        <RelativeTime className="text-primary tabular-nums" value={value} />
      </div>
    ))}
  </div>
)

export const Empty = () => (
  <div className="flex w-64 items-center justify-between gap-6 text-sm">
    <span className="text-secondary">Last deploy</span>
    <RelativeTime className="text-tertiary" value={null} />
  </div>
)
