import { type ReactNode, useEffect, useRef, useState } from 'react'

import { Combobox, Label } from 'imbi-ui'

const TEAMS = [
  { label: 'Platform Engineering', value: 'platform' },
  { label: 'Data Services', value: 'data' },
  { label: 'Messaging', value: 'messaging' },
  { label: 'Deliverability', value: 'deliverability' },
  { label: 'Site Reliability', value: 'sre' },
  { label: 'Web Experience', value: 'web' },
]

const PROJECT_TYPES = [
  { label: 'HTTP API', value: 'http-api' },
  { label: 'Queue Consumer', value: 'consumer' },
  { label: 'Scheduled Job', value: 'scheduled-job' },
  { label: 'Python Library', value: 'python-library' },
]

// Combobox keeps its open state internally; click the trigger once on
// mount so the card shows the open search list.
const PreviewOnlyAutoOpen = ({ children }: { children: ReactNode }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current
      ?.querySelector<HTMLButtonElement>('button[role="combobox"]')
      ?.click()
  }, [])
  return <div ref={ref}>{children}</div>
}

export const TeamOpen = () => {
  const [team, setTeam] = useState('platform')
  return (
    <div className="grid w-80 gap-2">
      <Label htmlFor="team">Team</Label>
      <PreviewOnlyAutoOpen>
        <Combobox
          id="team"
          onChange={setTeam}
          options={TEAMS}
          placeholder="Select team..."
          value={team}
        />
      </PreviewOnlyAutoOpen>
    </div>
  )
}

export const ClosedPlaceholder = () => {
  const [type, setType] = useState('')
  return (
    <div className="grid w-80 gap-2">
      <Label htmlFor="project-type">Project type</Label>
      <Combobox
        id="project-type"
        onChange={setType}
        options={PROJECT_TYPES}
        placeholder="Select project type..."
        value={type}
      />
    </div>
  )
}

export const ClosedWithValue = () => {
  const [type, setType] = useState('http-api')
  return (
    <div className="grid w-80 gap-2">
      <Label htmlFor="project-type-set">Project type</Label>
      <Combobox
        id="project-type-set"
        onChange={setType}
        options={PROJECT_TYPES}
        placeholder="Select project type..."
        value={type}
      />
    </div>
  )
}

export const Disabled = () => (
  <div className="grid w-80 gap-2">
    <Label htmlFor="environment">Environment</Label>
    <Combobox
      disabled
      id="environment"
      onChange={() => {}}
      options={[]}
      placeholder="Select a project first..."
      value=""
    />
  </div>
)
