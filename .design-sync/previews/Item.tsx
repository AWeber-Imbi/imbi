import {
  Button,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from 'imbi-ui'
import { GitBranch, Plug, Rocket, Server } from 'lucide-react'

export const ConnectIdentity = () => (
  <div className="w-full max-w-2xl">
    <Item
      className="border-amber-border bg-amber-bg/40"
      size="sm"
      variant="outline"
    >
      <ItemMedia variant="icon">
        <Plug className="size-4" />
      </ItemMedia>
      <ItemContent>
        <ItemTitle>Not connected to GitHub</ItemTitle>
        <ItemDescription>Connect your account to deploy imbi-api.</ItemDescription>
      </ItemContent>
      <ItemActions>
        <Button
          className="text-secondary hover:text-primary h-auto p-0 text-xs font-medium hover:no-underline"
          variant="link"
        >
          Manage
        </Button>
        <Button className="h-8 gap-2 text-xs" size="sm">
          <Plug className="size-3.5" />
          Connect GitHub
        </Button>
      </ItemActions>
    </Item>
  </div>
)

export const Variants = () => (
  <div className="flex w-full max-w-xl flex-col gap-3">
    <Item>
      <ItemMedia variant="icon">
        <Server className="size-4" />
      </ItemMedia>
      <ItemContent>
        <ItemTitle>default</ItemTitle>
        <ItemDescription>Transparent background, no border.</ItemDescription>
      </ItemContent>
    </Item>
    <Item variant="outline">
      <ItemMedia variant="icon">
        <Server className="size-4" />
      </ItemMedia>
      <ItemContent>
        <ItemTitle>outline</ItemTitle>
        <ItemDescription>Bordered row for standalone prompts.</ItemDescription>
      </ItemContent>
    </Item>
    <Item variant="muted">
      <ItemMedia variant="icon">
        <Server className="size-4" />
      </ItemMedia>
      <ItemContent>
        <ItemTitle>muted</ItemTitle>
        <ItemDescription>Subtle filled background.</ItemDescription>
      </ItemContent>
    </Item>
  </div>
)

export const GroupSmall = () => (
  <ItemGroup className="w-full max-w-xl gap-2">
    <Item size="sm" variant="outline">
      <ItemMedia>
        <Rocket />
      </ItemMedia>
      <ItemContent>
        <ItemTitle>imbi-api 2.35.1 to production</ItemTitle>
        <ItemDescription>Deployed 12 minutes ago by gavinr</ItemDescription>
      </ItemContent>
      <ItemActions>
        <Button size="sm" variant="outline">
          View
        </Button>
      </ItemActions>
    </Item>
    <Item size="sm" variant="outline">
      <ItemMedia>
        <GitBranch />
      </ItemMedia>
      <ItemContent>
        <ItemTitle>imbi-gateway 1.8.4 to staging</ItemTitle>
        <ItemDescription>Deployed 3 hours ago by release-bot</ItemDescription>
      </ItemContent>
      <ItemActions>
        <Button size="sm" variant="outline">
          View
        </Button>
      </ItemActions>
    </Item>
  </ItemGroup>
)
