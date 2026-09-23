import { useState } from 'react'

import type { Meta, StoryObj } from '@storybook/react-vite'

import { SegmentedControl, SegmentedControlItem } from './segmented-control'

const meta = {
  args: { ariaLabel: 'Time range', onValueChange: () => {}, value: '7d' },
  component: SegmentedControl,
  title: 'UI/SegmentedControl',
} satisfies Meta<typeof SegmentedControl>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {
  render: function Render(args) {
    const [value, setValue] = useState(args.value)
    return (
      <SegmentedControl {...args} onValueChange={setValue} value={value}>
        <SegmentedControlItem value="24h">24h</SegmentedControlItem>
        <SegmentedControlItem value="7d">7 days</SegmentedControlItem>
        <SegmentedControlItem value="30d">30 days</SegmentedControlItem>
      </SegmentedControl>
    )
  },
}
