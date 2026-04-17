interface StatWidgetProps {
  title: string
  value: string
  icon: string
}

export function StatWidget({ title, value, icon }: StatWidgetProps) {
  return (
    <div className={`rounded-lg p-6 ${'border border-border bg-card'}`}>
      <div className="flex items-center justify-between">
        <div>
          <p className={'text-sm text-secondary'}>{title}</p>
          <p className={'mt-2 text-3xl text-primary'}>{value}</p>
        </div>
        <div className="text-4xl">{icon}</div>
      </div>
    </div>
  )
}
