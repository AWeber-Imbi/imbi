import { useState } from 'react'

import { ColorPicker, Input, Label } from 'imbi-ui'

export const EnvironmentSwatch = () => {
  const [name, setName] = useState('Production')
  const [color, setColor] = useState('#C86B5E')
  return (
    <div className="w-full max-w-md space-y-4">
      <div className="grid gap-2">
        <Label htmlFor="env-name">Name</Label>
        <Input
          id="env-name"
          onChange={(e) => setName(e.target.value)}
          value={name}
        />
      </div>
      <ColorPicker
        labelValue={name}
        objectType="environment"
        onChange={setColor}
        value={color}
      />
    </div>
  )
}

export const CustomHex = () => {
  const [color, setColor] = useState('#2F8F83')
  return (
    <div className="w-full max-w-md">
      <ColorPicker
        labelValue="HTTP API"
        objectType="project type"
        onChange={setColor}
        value={color}
      />
    </div>
  )
}

export const LowContrast = () => {
  const [color, setColor] = useState('#E8E26A')
  return (
    <div className="w-full max-w-md">
      <ColorPicker
        labelValue="Staging"
        objectType="environment"
        onChange={setColor}
        value={color}
      />
    </div>
  )
}
