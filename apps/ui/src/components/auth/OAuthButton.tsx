import {
  Github as GitHubIcon,
  Mail as GoogleIcon,
  Key as KeyIcon,
  LucideIcon,
  Clock as OIDCIcon,
} from 'lucide-react'

import { Button } from '@/components/ui/button'

interface OAuthButtonProps {
  disabled?: boolean
  onClick: () => void
  provider: {
    icon?: null | string
    id: string
    name: string
  }
}

const iconMap: Record<string, LucideIcon> = {
  github: GitHubIcon,
  google: GoogleIcon,
  key: KeyIcon,
  oidc: OIDCIcon,
}

export function OAuthButton({ disabled, onClick, provider }: OAuthButtonProps) {
  const Icon = iconMap[provider.icon ?? ''] || KeyIcon

  return (
    <Button
      className="w-full gap-2"
      disabled={disabled}
      onClick={onClick}
      variant="outline"
    >
      <Icon className="h-4 w-4" />
      Continue with {provider.name}
    </Button>
  )
}
