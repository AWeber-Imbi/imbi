interface LoadingStateProps {
  className?: string
  label: string
}

export function LoadingState({ className, label }: LoadingStateProps) {
  return (
    <div className={className ?? 'flex items-center justify-center py-12'}>
      <div className="text-secondary text-sm">{label}</div>
    </div>
  )
}
