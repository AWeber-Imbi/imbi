import { Plus, X } from 'lucide-react'

import { Input } from '@/components/ui/input'

interface BlueprintUiMapEditorProps {
  commit: (next: [string, string][]) => void
  defaultVal: string
  entries: [string, string][]
  isColor: boolean
  keyPh: string
  label: string
  mapType: string
  setEntries: (next: [string, string][]) => void
  valPh: string
}

export function BlueprintUiMapEditor({
  commit,
  defaultVal,
  entries,
  isColor,
  keyPh,
  label: mapLabel,
  mapType,
  setEntries,
  valPh,
}: BlueprintUiMapEditorProps) {
  return (
    <div key={mapType}>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-xs text-secondary">{mapLabel}</label>
        <button
          className={
            'hover:text-info/80 flex items-center gap-1 text-xs text-info'
          }
          onClick={() => {
            setEntries([...entries, ['', defaultVal]])
          }}
          type="button"
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
            <div className="flex items-center gap-1.5" key={idx}>
              <Input
                className="flex-1 text-xs"
                onBlur={() => commit(entries)}
                onChange={(e) => {
                  const next = entries.map((row, i): [string, string] =>
                    i === idx ? [e.target.value, row[1]] : row,
                  )
                  setEntries(next)
                }}
                placeholder={keyPh}
                value={eKey}
              />
              {isColor ? (
                <select
                  className="rounded-md border border-input bg-background px-2 py-1.5 text-xs text-foreground"
                  onChange={(e) => {
                    const next = entries.map((row, i): [string, string] =>
                      i === idx ? [row[0], e.target.value] : row,
                    )
                    setEntries(next)
                    commit(next)
                  }}
                  value={eVal}
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
                  className="flex-1 text-xs"
                  onBlur={() => commit(entries)}
                  onChange={(e) => {
                    const next = entries.map((row, i): [string, string] =>
                      i === idx ? [row[0], e.target.value] : row,
                    )
                    setEntries(next)
                  }}
                  placeholder={valPh}
                  value={eVal}
                />
              )}
              <button
                className={'flex-shrink-0 text-tertiary hover:text-danger'}
                onClick={() => {
                  const next = entries.filter((_, i) => i !== idx)
                  setEntries(next)
                  commit(next)
                }}
                type="button"
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
