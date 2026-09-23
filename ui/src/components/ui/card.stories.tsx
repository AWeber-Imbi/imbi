import type { Meta, StoryObj } from '@storybook/react-vite'

import { Button } from './button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from './card'

const meta = {
  component: Card,
  title: 'UI/Card',
} satisfies Meta<typeof Card>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {
  render: (args) => (
    <Card {...args} className="w-96">
      <CardHeader>
        <CardTitle>Deployments</CardTitle>
        <CardDescription>Recent releases across environments</CardDescription>
      </CardHeader>
      <CardContent className="text-secondary text-sm">
        3 deployments in the last 24 hours.
      </CardContent>
      <CardFooter className="justify-end">
        <Button size="sm" variant="outline">
          View all
        </Button>
      </CardFooter>
    </Card>
  ),
}
