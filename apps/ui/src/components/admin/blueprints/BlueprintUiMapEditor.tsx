import { Plus, X } from 'lucide-react'

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

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
        <Label className="text-secondary text-xs">{mapLabel}</Label>
        <button
          className={
            'text-info hover:text-info/80 flex items-center gap-1 text-xs'
          }
          onClick={() => {
            setEntries([...entries, ['', defaultVal]])
          }}
          type="button"
        >
          <Plus className="size-3" />
          Add entry
        </button>
      </div>
      {entries.length === 0 ? (
        <p className="text-tertiary text-xs italic">
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
                <Select
                  onValueChange={(v) => {
                    const next = entries.map((row, i): [string, string] =>
                      i === idx ? [row[0], v] : row,
                    )
                    setEntries(next)
                    commit(next)
                  }}
                  value={eVal}
                >
                  <SelectTrigger
                    aria-label="Color"
                    className="h-8 w-auto text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {['green', 'red', 'amber', 'yellow', 'blue', 'gray'].map(
                      (c) => (
                        <SelectItem key={c} value={c}>
                          {c}
                        </SelectItem>
                      ),
                    )}
                  </SelectContent>
                </Select>
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
                className={'text-tertiary hover:text-danger shrink-0'}
                onClick={() => {
                  const next = entries.filter((_, i) => i !== idx)
                  setEntries(next)
                  commit(next)
                }}
                type="button"
              >
                <X className="size-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
