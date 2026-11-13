export function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-tertiary text-xs">{label}</span>
      <pre className="bg-secondary rounded-md p-3 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
        {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}
