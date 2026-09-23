import { Badge } from 'imbi-ui'

const VARIANTS = [
  'default',
  'secondary',
  'outline',
  'neutral',
  'accent',
  'info',
  'success',
  'warning',
  'danger',
  'destructive',
] as const

export const Default = () => <Badge>production</Badge>

export const AllVariants = () => (
  <div className="flex flex-wrap gap-2">
    {VARIANTS.map((variant) => (
      <Badge key={variant} variant={variant}>
        {variant}
      </Badge>
    ))}
  </div>
)

export const EnvironmentStatus = () => (
  <div className="flex w-64 flex-col gap-2 text-sm">
    <div className="flex items-center justify-between gap-6">
      <span className="text-primary">production</span>
      <Badge variant="success">Healthy</Badge>
    </div>
    <div className="flex items-center justify-between gap-6">
      <span className="text-primary">staging</span>
      <Badge variant="warning">Degraded</Badge>
    </div>
    <div className="flex items-center justify-between gap-6">
      <span className="text-primary">testing</span>
      <Badge variant="danger">Failed</Badge>
    </div>
  </div>
)

export const ProjectTags = () => (
  <div className="flex flex-wrap items-center gap-2">
    <Badge variant="secondary">python</Badge>
    <Badge variant="secondary">fastapi</Badge>
    <Badge variant="outline">api</Badge>
    <Badge variant="info">v2.35.1</Badge>
  </div>
)
