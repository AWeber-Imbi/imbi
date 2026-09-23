import { useState } from 'react'

import { IconPicker, Label } from 'imbi-ui'

export const Selected = () => {
  const [icon, setIcon] = useState('lucide-server')
  return (
    <div className="grid w-80 gap-2">
      <Label>Icon</Label>
      <IconPicker onChange={setIcon} value={icon} />
    </div>
  )
}

export const Empty = () => {
  const [icon, setIcon] = useState('')
  return (
    <div className="grid w-80 gap-2">
      <Label>Icon</Label>
      <IconPicker onChange={setIcon} value={icon} />
    </div>
  )
}

export const Database = () => {
  const [icon, setIcon] = useState('lucide-database')
  return (
    <div className="grid w-80 gap-2">
      <Label>Project type icon</Label>
      <IconPicker onChange={setIcon} value={icon} />
      <p className="text-tertiary text-xs">
        Shown next to every project of this type.
      </p>
    </div>
  )
}
