import { Plug } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { EntityIcon } from '@/components/ui/entity-icon'
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from '@/components/ui/item'

interface ConnectIdentityPromptProps {
  // What the actor is blocked from doing, used in the description copy.
  action: 'deploy' | 'release'
  // Identity provider display label (e.g. "GitHub Enterprise Cloud").
  label: string
  // Start the connection flow for this provider.
  onConnect: () => void
  // Open the connections management page.
  onManage: () => void
  // Icon of the service backing the provider; falls back to a plug glyph.
  serviceIcon: null | string
}

// Compact prompt shown at the top of the Deployments / Releases tabs when the
// actor has no active identity connection to the provider that powers the
// deploy/release action.
export function ConnectIdentityPrompt({
  action,
  label,
  onConnect,
  onManage,
  serviceIcon,
}: ConnectIdentityPromptProps) {
  const target =
    action === 'release'
      ? 'cut releases for this project'
      : 'deploy this project'

  return (
    <Item
      className="border-amber-border bg-amber-bg/40"
      size="sm"
      variant="outline"
    >
      <ItemMedia variant="icon">
        {serviceIcon ? (
          <EntityIcon className="size-4" icon={serviceIcon} />
        ) : (
          <Plug className="size-4" />
        )}
      </ItemMedia>
      <ItemContent>
        <ItemTitle>Not connected to {label}</ItemTitle>
        <ItemDescription>Connect your account to {target}.</ItemDescription>
      </ItemContent>
      <ItemActions>
        <Button
          className="text-secondary hover:text-primary h-auto p-0 text-xs font-medium hover:no-underline"
          onClick={onManage}
          type="button"
          variant="link"
        >
          Manage
        </Button>
        <Button className="h-8 gap-2 text-xs" onClick={onConnect} size="sm">
          <Plug className="size-3.5" />
          Connect {label}
        </Button>
      </ItemActions>
    </Item>
  )
}
