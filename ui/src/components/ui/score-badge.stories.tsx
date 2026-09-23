import type { Meta, StoryObj } from '@storybook/react-vite'

import { ScoreBadge } from './score-badge'

const meta = {
  args: { score: 86, size: 'sm', variant: 'circle' },
  argTypes: {
    score: { control: { max: 100, min: 0, type: 'range' } },
    size: { control: 'inline-radio', options: ['sm', 'md', 'lg', 'xl'] },
    variant: { control: 'inline-radio', options: ['circle', 'square'] },
  },
  component: ScoreBadge,
  title: 'UI/ScoreBadge',
} satisfies Meta<typeof ScoreBadge>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const NoScore: Story = { args: { score: null } }

export const Thresholds: Story = {
  render: (args) => (
    <div className="flex items-center gap-3">
      <ScoreBadge {...args} score={92} />
      <ScoreBadge {...args} score={74} />
      <ScoreBadge {...args} score={41} />
      <ScoreBadge {...args} score={null} />
    </div>
  ),
}

export const Sizes: Story = {
  render: (args) => (
    <div className="flex items-center gap-3">
      <ScoreBadge {...args} size="sm" />
      <ScoreBadge {...args} size="md" />
      <ScoreBadge {...args} size="lg" />
      <ScoreBadge {...args} size="xl" />
    </div>
  ),
}
