import { useState } from 'react'

import { Code, List } from 'lucide-react'
import { SegmentedControl, SegmentedControlItem } from 'imbi-ui'

export const Default = () => {
  const [value, setValue] = useState('7d')
  return (
    <SegmentedControl
      ariaLabel="Time range"
      onValueChange={setValue}
      value={value}
    >
      <SegmentedControlItem value="24h">24h</SegmentedControlItem>
      <SegmentedControlItem value="7d">7 days</SegmentedControlItem>
      <SegmentedControlItem value="30d">30 days</SegmentedControlItem>
    </SegmentedControl>
  )
}

export const WithCounts = () => {
  const [value, setValue] = useState('')
  return (
    <SegmentedControl
      ariaLabel="Filter by outcome"
      onValueChange={setValue}
      value={value}
    >
      <SegmentedControlItem value="">All</SegmentedControlItem>
      <SegmentedControlItem value="succeeded">succeeded 42</SegmentedControlItem>
      <SegmentedControlItem value="skipped">skipped 7</SegmentedControlItem>
      <SegmentedControlItem value="failed">failed 3</SegmentedControlItem>
    </SegmentedControl>
  )
}

export const WithIcons = () => {
  const [value, setValue] = useState('visual')
  return (
    <SegmentedControl
      ariaLabel="Editor mode"
      onValueChange={setValue}
      value={value}
    >
      <SegmentedControlItem className="px-3 py-1.5 text-sm" value="visual">
        <List className="size-3.5" />
        Visual
      </SegmentedControlItem>
      <SegmentedControlItem className="px-3 py-1.5 text-sm" value="code">
        <Code className="size-3.5" />
        Code
      </SegmentedControlItem>
    </SegmentedControl>
  )
}

export const InToolbar = () => {
  const [value, setValue] = useState('user')
  return (
    <div className="flex w-80 items-center justify-between gap-6">
      <span className="text-primary text-sm font-medium">Account type</span>
      <SegmentedControl
        ariaLabel="Account type"
        onValueChange={setValue}
        value={value}
      >
        <SegmentedControlItem value="user">User</SegmentedControlItem>
        <SegmentedControlItem value="admin">Admin</SegmentedControlItem>
      </SegmentedControl>
    </div>
  )
}
