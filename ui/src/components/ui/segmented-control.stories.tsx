import type { Meta, StoryObj } from '@storybook/react-vite'
import { useArgs } from 'storybook/preview-api'
import { fn } from 'storybook/test'

import { SegmentedControl, SegmentedControlItem } from './segmented-control'

const meta = {
  args: { ariaLabel: 'Time range', onValueChange: fn(), value: '7d' },
  component: SegmentedControl,
  title: 'UI/SegmentedControl',
} satisfies Meta<typeof SegmentedControl>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {
  render: function Render(args) {
    // Route selection through the story's args so clicking a segment and
    // editing `value` in Controls stay in sync.
    const [, updateArgs] = useArgs<typeof args>()
    return (
      <SegmentedControl
        {...args}
        onValueChange={(value) => {
          args.onValueChange(value)
          updateArgs({ value })
        }}
      >
        <SegmentedControlItem value="24h">24h</SegmentedControlItem>
        <SegmentedControlItem value="7d">7 days</SegmentedControlItem>
        <SegmentedControlItem value="30d">30 days</SegmentedControlItem>
      </SegmentedControl>
    )
  },
}
