import { Checkbox, Input, Label, RequiredAsterisk } from 'imbi-ui'

export const Default = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="team-name">Team name</Label>
    <Input defaultValue="Platform Engineering" id="team-name" />
  </div>
)

export const Required = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="environment">
      Environment <RequiredAsterisk />
    </Label>
    <Input id="environment" placeholder="production" />
  </div>
)

export const WithCheckbox = () => (
  <div className="flex items-center gap-2">
    <Checkbox defaultChecked id="notify-deploys" />
    <Label htmlFor="notify-deploys">Notify on production deploys</Label>
  </div>
)

export const PeerDisabled = () => (
  <div className="flex items-center gap-2">
    <Checkbox disabled id="auto-archive" />
    <Label htmlFor="auto-archive">Archive stale projects automatically</Label>
  </div>
)

export const Muted = () => (
  <div className="w-80">
    <Label className="text-muted-foreground mb-1.5 block text-xs">
      Similarity threshold
    </Label>
    <p className="text-primary font-mono text-sm">0.75 cosine</p>
  </div>
)
