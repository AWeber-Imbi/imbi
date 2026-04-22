interface LoadingStateProps {
  label: string
  className?: string
}

export function LoadingState({ label, className }: LoadingStateProps) {
  return (
    <div className={className ?? 'flex items-center justify-center py-12'}>
      <div className="text-sm text-secondary">{label}</div>
    </div>
  )
}
