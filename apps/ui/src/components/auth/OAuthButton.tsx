import { Button } from '@/components/ui/button'
import {
  LucideIcon,
  Mail as GoogleIcon,
  Github as GitHubIcon,
  Clock as OIDCIcon,
  Key as KeyIcon,
} from 'lucide-react'

interface OAuthButtonProps {
  provider: {
    id: string
    name: string
    icon: string
  }
  onClick: () => void
  disabled?: boolean
}

const iconMap: Record<string, LucideIcon> = {
  google: GoogleIcon,
  github: GitHubIcon,
  oidc: OIDCIcon,
  key: KeyIcon,
}

export function OAuthButton({ provider, onClick, disabled }: OAuthButtonProps) {
  const Icon = iconMap[provider.icon] || KeyIcon

  return (
    <Button
      variant="outline"
      className="w-full gap-2"
      onClick={onClick}
      disabled={disabled}
    >
      <Icon className="w-4 h-4" />
      Continue with {provider.name}
    </Button>
  )
}
