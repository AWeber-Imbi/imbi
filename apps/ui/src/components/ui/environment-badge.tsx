interface EnvironmentBadgeProps {
  name: string
  slug: string
  label_color?: string | null
}

export function EnvironmentBadge({
  name,
  slug,
  label_color,
}: EnvironmentBadgeProps) {
  return (
    <span
      key={slug}
      className="rounded px-2 py-1 text-xs font-medium"
      style={
        label_color
          ? {
              backgroundColor: label_color + '20',
              color: label_color,
              border: `1px solid ${label_color}40`,
            }
          : undefined
      }
    >
      {name}
    </span>
  )
}
