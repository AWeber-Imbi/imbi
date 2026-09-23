import { Input, Label, RequiredAsterisk, Textarea } from 'imbi-ui'

export const Default = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="new-project-name">
      Name <RequiredAsterisk />
    </Label>
    <Input aria-required id="new-project-name" placeholder="e.g. imbi-api" />
  </div>
)

export const MixedFields = () => (
  <div className="w-80 space-y-4">
    <div className="space-y-2">
      <Label htmlFor="ops-project">
        Project <RequiredAsterisk />
      </Label>
      <Input aria-required defaultValue="imbi-gateway" id="ops-project" />
    </div>
    <div className="space-y-2">
      <Label htmlFor="ops-ticket">Ticket URL</Label>
      <Input id="ops-ticket" placeholder="e.g. OPS-1234" />
    </div>
    <div className="space-y-2">
      <Label htmlFor="ops-desc">
        Description <RequiredAsterisk />
      </Label>
      <Textarea
        aria-required
        className="min-h-24 resize-none"
        id="ops-desc"
        placeholder="Short summary of what was done"
      />
    </div>
  </div>
)
