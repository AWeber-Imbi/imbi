import { Plus, X } from 'lucide-react'
import { Input } from '@/components/ui/input'

interface BlueprintUiMapEditorProps {
  mapType: string
  label: string
  keyPh: string
  valPh: string
  defaultVal: string
  isColor: boolean
  entries: [string, string][]
  setEntries: (next: [string, string][]) => void
  commit: (next: [string, string][]) => void
}

export function BlueprintUiMapEditor({
  mapType,
  label: mapLabel,
  keyPh,
  valPh,
  defaultVal,
  isColor,
  entries,
  setEntries,
  commit,
}: BlueprintUiMapEditorProps) {
  return (
    <div key={mapType}>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-xs text-secondary">{mapLabel}</label>
        <button
          type="button"
          onClick={() => {
            setEntries([...entries, ['', defaultVal]])
          }}
          className={
            'hover:text-info/80 flex items-center gap-1 text-xs text-info'
          }
        >
          <Plus className="h-3 w-3" />
          Add entry
        </button>
      </div>
      {entries.length === 0 ? (
        <p className="text-xs italic text-tertiary">
          No {mapLabel.toLowerCase()} entries
        </p>
      ) : (
        <div className="space-y-1.5">
          {entries.map(([eKey, eVal], idx) => (
            <div key={idx} className="flex items-center gap-1.5">
              <Input
                value={eKey}
                onChange={(e) => {
                  const next = entries.map((row, i): [string, string] =>
                    i === idx ? [e.target.value, row[1]] : row,
                  )
                  setEntries(next)
                }}
                onBlur={() => commit(entries)}
                placeholder={keyPh}
                className="flex-1 text-xs"
              />
              {isColor ? (
                <select
                  value={eVal}
                  onChange={(e) => {
                    const next = entries.map((row, i): [string, string] =>
                      i === idx ? [row[0], e.target.value] : row,
                    )
                    setEntries(next)
                    commit(next)
                  }}
                  className="rounded-md border border-input bg-background px-2 py-1.5 text-xs text-foreground"
                >
                  {['green', 'red', 'amber', 'yellow', 'blue', 'gray'].map(
                    (c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ),
                  )}
                </select>
              ) : (
                <Input
                  value={eVal}
                  onChange={(e) => {
                    const next = entries.map((row, i): [string, string] =>
                      i === idx ? [row[0], e.target.value] : row,
                    )
                    setEntries(next)
                  }}
                  onBlur={() => commit(entries)}
                  placeholder={valPh}
                  className="flex-1 text-xs"
                />
              )}
              <button
                type="button"
                onClick={() => {
                  const next = entries.filter((_, i) => i !== idx)
                  setEntries(next)
                  commit(next)
                }}
                className={'flex-shrink-0 text-tertiary hover:text-danger'}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
