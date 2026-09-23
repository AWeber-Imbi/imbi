import { StatCard } from 'imbi-ui'

export const Default = () => (
  <div className="w-56">
    <StatCard label="Projects affected" value="18" />
  </div>
)

export const ValueColors = () => (
  <div className="grid grid-cols-3 gap-3">
    <StatCard
      label="Forbidden versions"
      value="4"
      valueColor="var(--text-color-danger)"
    />
    <StatCard
      label="Deprecated versions"
      value="11"
      valueColor="var(--text-color-warning)"
    />
    <StatCard
      label="Org avg score"
      value="82"
      valueColor="var(--text-color-success)"
    />
  </div>
)

export const ReportRow = () => (
  <div className="grid grid-cols-4 gap-3">
    <StatCard label="Projects affected" value="18" />
    <StatCard
      label="Forbidden versions"
      value="4"
      valueColor="var(--text-color-danger)"
    />
    <StatCard label="Deprecated versions" value="11" />
    <StatCard label="Known advisories" value="7" />
  </div>
)

export const Loading = () => (
  <div className="w-56">
    <StatCard label="Teams tracked" value="—" />
  </div>
)
