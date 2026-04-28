interface StatWidgetProps {
  icon: string
  title: string
  value: string
}

export function StatWidget({ icon, title, value }: StatWidgetProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-secondary">{title}</p>
          <p className="mt-2 text-3xl text-primary">{value}</p>
        </div>
        <div className="text-4xl">{icon}</div>
      </div>
    </div>
  )
}
