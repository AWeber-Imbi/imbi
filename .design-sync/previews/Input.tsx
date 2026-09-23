import { Search } from 'lucide-react'
import { Input, Label, RequiredAsterisk } from 'imbi-ui'

export const Default = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="project-name">
      Name <RequiredAsterisk />
    </Label>
    <Input id="project-name" placeholder="e.g. imbi-api" />
  </div>
)

export const Filled = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="project-slug">Slug</Label>
    <Input className="font-mono" defaultValue="imbi-api" id="project-slug" />
  </div>
)

export const Types = () => (
  <div className="w-80 space-y-4">
    <div className="space-y-2">
      <Label htmlFor="owner-email">Owner email</Label>
      <Input
        defaultValue="platform-team@example.com"
        id="owner-email"
        type="email"
      />
    </div>
    <div className="space-y-2">
      <Label htmlFor="api-token">API token</Label>
      <Input defaultValue="imbi_pat_7f3a9c21" id="api-token" type="password" />
    </div>
    <div className="space-y-2">
      <Label htmlFor="replicas">Replicas</Label>
      <Input defaultValue={3} id="replicas" min={1} type="number" />
    </div>
  </div>
)

export const WithIcon = () => (
  <div className="relative w-80">
    <Search className="text-tertiary pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
    <Input aria-label="Search projects" className="pl-9" placeholder="Search projects..." />
  </div>
)

export const Invalid = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="repo-url">Repository URL</Label>
    <Input
      aria-invalid
      className="border-red-500"
      defaultValue="github.com/aweber/imbi-api"
      id="repo-url"
    />
    <p className="text-sm text-red-600">Enter a full URL starting with https://</p>
  </div>
)

export const Disabled = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="project-id">Project ID</Label>
    <Input
      className="font-mono"
      defaultValue="prj_01HZX4K7Q2"
      disabled
      id="project-id"
    />
  </div>
)
