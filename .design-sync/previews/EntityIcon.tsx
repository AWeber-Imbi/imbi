import { EntityIcon } from 'imbi-ui'

const ICONS = ['lucide-server', 'lucide-database', 'lucide-globe', 'lucide-git-branch', 'lucide-package', 'lucide-shield']

export const LucideIcons = () => (
  <div className="flex items-center gap-4">
    {ICONS.map((icon) => (
      <EntityIcon className="text-foreground size-6" icon={icon} key={icon} />
    ))}
  </div>
)

export const Sizes = () => (
  <div className="flex items-end gap-4">
    <EntityIcon className="size-4" icon="lucide-server" />
    <EntityIcon className="size-6" icon="lucide-server" />
    <EntityIcon className="size-8" icon="lucide-server" />
  </div>
)

export const InText = () => (
  <div className="text-foreground flex items-center gap-2 text-sm">
    <EntityIcon className="size-4" icon="lucide-database" />
    <span>imbi-postgres</span>
  </div>
)
