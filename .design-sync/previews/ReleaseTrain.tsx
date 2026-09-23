import { ReleaseTrain } from 'imbi-ui'

const env = (slug: string, name: string, sort_order: number, label_color: string) =>
  ({
    allow_autonomous: false,
    can_deploy: true,
    can_promote: slug !== 'production',
    description: null,
    icon: null,
    label_color,
    name,
    slug,
    sort_order,
    terminal: slug === 'production',
    updated_at: null,
  }) as never

const TESTING = env('testing', 'Testing', 10, '#5A89C9')
const STAGING = env('staging', 'Staging', 20, '#C9A227')
const PRODUCTION = env('production', 'Production', 30, '#C86B5E')

export const Default = () => (
  <ReleaseTrain
    stops={[
      { environment: TESTING, value: '2.35.1' },
      { environment: STAGING, value: '2.35.1' },
      { environment: PRODUCTION, value: '2.35.0' },
    ]}
  />
)

export const PendingPromotion = () => (
  <ReleaseTrain
    stops={[
      { environment: TESTING, value: '2.36.0' },
      { environment: STAGING, value: null },
      { environment: PRODUCTION, value: null },
    ]}
  />
)

export const Compact = () => (
  <ReleaseTrain
    size="compact"
    stops={[
      { environment: TESTING, value: 'a41f9c2' },
      { environment: STAGING, value: 'a41f9c2' },
      { environment: PRODUCTION, value: null },
    ]}
  />
)

export const DoneWithoutValue = () => (
  <ReleaseTrain
    size="compact"
    stops={[
      { done: true, environment: TESTING },
      { done: true, environment: STAGING },
      { environment: PRODUCTION },
    ]}
  />
)
