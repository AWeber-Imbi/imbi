/**
 * Vitest auto-mock for the Cypher editor. Replaces CodeMirror with a plain
 * textarea so component tests can drive the input via userEvent — the real
 * editor is exercised by manual smoke tests.
 */
interface CypherEditorMockProps {
  onChange: (v: string) => void
  onSubmit: () => void
  value: string
}

export function CypherEditor({
  onChange,
  onSubmit,
  value,
}: CypherEditorMockProps) {
  return (
    <textarea
      aria-label="Cypher query"
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
          e.preventDefault()
          onSubmit()
        }
      }}
      value={value}
    />
  )
}
