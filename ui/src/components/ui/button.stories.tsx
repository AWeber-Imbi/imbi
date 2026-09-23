import type { Meta, StoryObj } from '@storybook/react-vite'
import { Plus } from 'lucide-react'

import { Button } from './button'

const meta = {
  args: { children: 'Save changes' },
  argTypes: {
    size: {
      control: 'inline-radio',
      options: ['default', 'sm', 'lg', 'icon'],
    },
    variant: {
      control: 'select',
      options: [
        'default',
        'destructive',
        'ghost',
        'link',
        'outline',
        'secondary',
      ],
    },
  },
  component: Button,
  title: 'UI/Button',
} satisfies Meta<typeof Button>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const Destructive: Story = {
  args: { children: 'Delete project', variant: 'destructive' },
}

export const Disabled: Story = { args: { disabled: true } }

export const WithIcon: Story = {
  args: {
    children: (
      <>
        <Plus />
        New project
      </>
    ),
  },
}

export const Variants: Story = {
  render: (args) => (
    <div className="flex flex-wrap items-center gap-3">
      <Button {...args}>Default</Button>
      <Button {...args} variant="secondary">
        Secondary
      </Button>
      <Button {...args} variant="outline">
        Outline
      </Button>
      <Button {...args} variant="ghost">
        Ghost
      </Button>
      <Button {...args} variant="link">
        Link
      </Button>
      <Button {...args} variant="destructive">
        Destructive
      </Button>
    </div>
  ),
}
