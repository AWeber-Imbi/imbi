import type { Meta, StoryObj } from '@storybook/react-vite'

import { Badge } from './badge'

const VARIANTS = [
  'default',
  'secondary',
  'outline',
  'neutral',
  'accent',
  'info',
  'success',
  'warning',
  'danger',
  'destructive',
] as const

const meta = {
  args: { children: 'production' },
  argTypes: {
    variant: { control: 'select', options: VARIANTS },
  },
  component: Badge,
  title: 'UI/Badge',
} satisfies Meta<typeof Badge>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const AllVariants: Story = {
  render: (args) => (
    <div className="flex flex-wrap gap-2">
      {VARIANTS.map((variant) => (
        <Badge {...args} key={variant} variant={variant}>
          {variant}
        </Badge>
      ))}
    </div>
  ),
}
