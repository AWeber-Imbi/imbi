import { ScoreBadge } from 'imbi-ui'

export const Default = () => <ScoreBadge score={86} />

export const NoScore = () => <ScoreBadge score={null} />

export const Thresholds = () => (
  <div className="flex items-center gap-3">
    <ScoreBadge score={92} />
    <ScoreBadge score={74} />
    <ScoreBadge score={41} />
    <ScoreBadge score={null} />
  </div>
)

export const Sizes = () => (
  <div className="flex items-center gap-3">
    <ScoreBadge score={86} size="sm" />
    <ScoreBadge score={86} size="md" />
    <ScoreBadge score={86} size="lg" />
    <ScoreBadge score={86} size="xl" />
  </div>
)

export const Square = () => (
  <div className="flex items-center gap-3">
    <ScoreBadge score={92} size="lg" variant="square" />
    <ScoreBadge score={74} size="lg" variant="square" />
    <ScoreBadge score={41} size="lg" variant="square" />
  </div>
)
