import { useState } from 'react'

import { KeyValueEditor, Label } from 'imbi-ui'

export const EnvironmentVariables = () => {
  const [value, setValue] = useState<Record<string, number | string>>({
    DATABASE_URL: 'postgresql://imbi@db.internal:5432/imbi',
    LOG_LEVEL: 'info',
    WORKER_COUNT: 4,
  })
  return (
    <div className="grid w-full max-w-xl gap-2">
      <Label>Environment variables</Label>
      <KeyValueEditor
        keyPlaceholder="Variable name"
        onChange={setValue}
        value={value}
        valuePlaceholder="Value"
      />
    </div>
  )
}

export const Empty = () => {
  const [value, setValue] = useState<Record<string, number | string>>({})
  return (
    <div className="grid w-full max-w-xl gap-2">
      <Label>Identifiers</Label>
      <KeyValueEditor
        keyPlaceholder="Identifier (e.g. sentry_project)"
        onChange={setValue}
        value={value}
        valuePlaceholder="Value"
      />
    </div>
  )
}

export const Disabled = () => (
  <div className="grid w-full max-w-xl gap-2">
    <Label>Labels</Label>
    <KeyValueEditor
      disabled
      onChange={() => {}}
      value={{ cost_center: 'eng-platform', tier: 1 }}
    />
  </div>
)
