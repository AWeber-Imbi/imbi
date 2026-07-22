import { Button } from '@/components/ui/button'
import { EntityIcon } from '@/components/ui/entity-icon'

interface OAuthButtonProps {
  disabled?: boolean
  onClick: () => void
  provider: {
    icon?: null | string
    id: string
    name: string
  }
}

export function OAuthButton({ disabled, onClick, provider }: OAuthButtonProps) {
  return (
    <Button
      className="w-full gap-2"
      disabled={disabled}
      onClick={onClick}
      variant="outline"
    >
      <EntityIcon className="size-4" icon={provider.icon ?? 'key-round'} />
      Login with {provider.name}
    </Button>
  )
}
