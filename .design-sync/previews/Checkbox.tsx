import { Checkbox, Label } from 'imbi-ui'

export const Default = () => (
  <div className="flex items-center gap-2">
    <Checkbox defaultChecked id="transfer-repo" />
    <Label htmlFor="transfer-repo">
      Also move the repository to the new location.
    </Label>
  </div>
)

export const States = () => (
  <div className="space-y-3">
    <div className="flex items-center gap-2">
      <Checkbox id="cb-unchecked" />
      <Label htmlFor="cb-unchecked">Unchecked</Label>
    </div>
    <div className="flex items-center gap-2">
      <Checkbox checked id="cb-checked" />
      <Label htmlFor="cb-checked">Checked</Label>
    </div>
    <div className="flex items-center gap-2">
      <Checkbox checked="indeterminate" id="cb-indeterminate" />
      <Label htmlFor="cb-indeterminate">Indeterminate</Label>
    </div>
    <div className="flex items-center gap-2">
      <Checkbox disabled id="cb-disabled" />
      <Label htmlFor="cb-disabled">Disabled</Label>
    </div>
    <div className="flex items-center gap-2">
      <Checkbox checked disabled id="cb-disabled-checked" />
      <Label htmlFor="cb-disabled-checked">Disabled, checked</Label>
    </div>
  </div>
)

export const DestructiveOption = () => (
  <label className="text-secondary flex w-96 items-center gap-2 text-sm">
    <Checkbox defaultChecked />
    <span>
      Also delete the associated repository -- uncheck to keep the GitHub
      repository.
    </span>
  </label>
)

const projects = [
  { checked: true, name: 'imbi-api', type: 'HTTP API' },
  { checked: true, name: 'imbi-gateway', type: 'HTTP API' },
  { checked: false, name: 'imbi-scheduler', type: 'Consumer' },
  { checked: false, name: 'imbi-ui', type: 'Web App' },
]

export const SelectionList = () => (
  <div className="border-tertiary w-96 divide-y rounded-lg border">
    {projects.map((p) => (
      <label className="flex items-center gap-3 px-3 py-2" key={p.name}>
        <Checkbox defaultChecked={p.checked} />
        <span className="text-primary min-w-0 flex-1 truncate text-sm font-medium">
          {p.name}
        </span>
        <span className="text-tertiary shrink-0 text-xs">{p.type}</span>
      </label>
    ))}
  </div>
)
