import { EnvironmentBadge } from 'imbi-ui'

export const Default = () => (
  <EnvironmentBadge label_color="#C86B5E" name="Production" slug="production" />
)

export const ProjectEnvironments = () => (
  <div className="flex flex-wrap items-center gap-1.5">
    <EnvironmentBadge label_color="#6B9A3F" name="Development" slug="development" />
    <EnvironmentBadge label_color="#5A89C9" name="Testing" slug="testing" />
    <EnvironmentBadge label_color="#C9A227" name="Staging" slug="staging" />
    <EnvironmentBadge label_color="#C86B5E" name="Production" slug="production" />
  </div>
)

export const WithoutLabelColor = () => (
  <div className="flex flex-wrap items-center gap-1.5">
    <EnvironmentBadge label_color={null} name="Sandbox" slug="sandbox" />
    <EnvironmentBadge label_color="#7A7873" name="Disaster Recovery" slug="dr" />
  </div>
)

export const InProjectRow = () => (
  <div className="flex w-96 items-center justify-between gap-6 text-sm">
    <span className="text-primary font-medium">imbi-gateway</span>
    <div className="flex items-center gap-1.5">
      <EnvironmentBadge label_color="#C9A227" name="Staging" slug="staging" />
      <EnvironmentBadge label_color="#C86B5E" name="Production" slug="production" />
    </div>
  </div>
)
