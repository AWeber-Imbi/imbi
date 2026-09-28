import type { Meta, StoryObj } from '@storybook/react-vite'
import { ScrollText, Server } from 'lucide-react'
import { fn } from 'storybook/test'

import { Badge } from './badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './tabs'

const meta = {
  args: { defaultValue: 'overview', onValueChange: fn() },
  component: Tabs,
  title: 'UI/Tabs',
} satisfies Meta<typeof Tabs>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {
  render: (args) => (
    <Tabs {...args}>
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="deployments">Deployments</TabsTrigger>
        <TabsTrigger value="settings">Settings</TabsTrigger>
      </TabsList>
      <TabsContent className="pt-4 text-sm" value="overview">
        Overview content
      </TabsContent>
      <TabsContent className="pt-4 text-sm" value="deployments">
        Deployments content
      </TabsContent>
      <TabsContent className="pt-4 text-sm" value="settings">
        Settings content
      </TabsContent>
    </Tabs>
  ),
}

// Icon + count badge triggers, with a not-yet-available tab disabled —
// the shape the admin screens use.
export const WithIconsAndDisabled: Story = {
  args: { defaultValue: 'mcp' },
  render: (args) => (
    <Tabs {...args}>
      <TabsList>
        <TabsTrigger value="mcp">
          <Server className="mr-2 size-4" />
          MCP Servers
          <Badge className="ml-2" variant="neutral">
            3
          </Badge>
        </TabsTrigger>
        <TabsTrigger disabled value="prompts">
          <ScrollText className="mr-2 size-4" />
          System Prompts
          <Badge className="ml-2" variant="neutral">
            Soon
          </Badge>
        </TabsTrigger>
      </TabsList>
      <TabsContent className="pt-4 text-sm" value="mcp">
        MCP server list
      </TabsContent>
    </Tabs>
  ),
}
