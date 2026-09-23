import { Label, Switch } from 'imbi-ui'

export const Default = () => (
  <div className="flex w-96 items-center justify-between">
    <div>
      <p className="text-primary text-[13.5px]">Email notifications</p>
      <p className="text-tertiary text-[12px]">
        Receive email updates about your projects
      </p>
    </div>
    <Switch aria-label="Email notifications" defaultChecked />
  </div>
)

export const States = () => (
  <div className="space-y-3">
    <div className="flex items-center gap-3">
      <Switch id="sw-off" />
      <Label htmlFor="sw-off">Off</Label>
    </div>
    <div className="flex items-center gap-3">
      <Switch defaultChecked id="sw-on" />
      <Label htmlFor="sw-on">On</Label>
    </div>
    <div className="flex items-center gap-3">
      <Switch disabled id="sw-disabled" />
      <Label htmlFor="sw-disabled">Disabled</Label>
    </div>
    <div className="flex items-center gap-3">
      <Switch defaultChecked disabled id="sw-disabled-on" />
      <Label htmlFor="sw-disabled-on">Disabled, on</Label>
    </div>
  </div>
)

const rows = [
  {
    checked: true,
    description: 'When a release is deployed to production',
    label: 'Deployments',
  },
  {
    checked: true,
    description: 'When a project score drops below 70',
    label: 'Score changes',
  },
  {
    checked: false,
    description: 'A weekly summary of Operations Log entries',
    label: 'Weekly digest',
  },
]

export const SettingsList = () => (
  <div className="w-96 space-y-4">
    {rows.map((r) => (
      <div className="flex items-center justify-between" key={r.label}>
        <div>
          <p className="text-primary text-[13.5px]">{r.label}</p>
          <p className="text-tertiary text-[12px]">{r.description}</p>
        </div>
        <Switch aria-label={r.label} defaultChecked={r.checked} />
      </div>
    ))}
  </div>
)
