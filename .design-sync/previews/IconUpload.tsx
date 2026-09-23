import { useState } from 'react'

import { IconUpload, Label } from 'imbi-ui'

export const Empty = () => {
  const [icon, setIcon] = useState('')
  return (
    <div className="grid w-80 gap-2">
      <Label>Organization icon</Label>
      <IconUpload onChange={setIcon} value={icon} />
    </div>
  )
}

export const SmallLimit = () => {
  const [icon, setIcon] = useState('')
  return (
    <div className="grid w-80 gap-2">
      <Label>Environment icon</Label>
      <IconUpload maxSizeKB={100} onChange={setIcon} value={icon} />
    </div>
  )
}
