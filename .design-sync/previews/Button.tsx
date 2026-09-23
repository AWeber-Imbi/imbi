import { Plus, Trash2 } from 'lucide-react'
import { Button } from 'imbi-ui'

export const Default = () => <Button>Save changes</Button>

export const Variants = () => (
  <div className="flex flex-wrap items-center gap-3">
    <Button>Default</Button>
    <Button variant="secondary">Secondary</Button>
    <Button variant="outline">Outline</Button>
    <Button variant="ghost">Ghost</Button>
    <Button variant="link">Link</Button>
    <Button variant="destructive">Destructive</Button>
  </div>
)

export const Sizes = () => (
  <div className="flex items-center gap-3">
    <Button size="sm">Small</Button>
    <Button>Default</Button>
    <Button size="lg">Large</Button>
    <Button aria-label="Add project" size="icon">
      <Plus />
    </Button>
  </div>
)

export const WithIcon = () => (
  <div className="flex items-center gap-3">
    <Button>
      <Plus />
      New project
    </Button>
    <Button variant="destructive">
      <Trash2 />
      Delete project
    </Button>
  </div>
)

export const Disabled = () => <Button disabled>Save changes</Button>
