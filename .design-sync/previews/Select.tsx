import {
  Label,
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from 'imbi-ui'

export const EnvironmentOpen = () => (
  <div className="grid w-80 gap-2">
    <Label htmlFor="deploy-environment">Environment</Label>
    <Select defaultOpen defaultValue="staging">
      <SelectTrigger id="deploy-environment">
        <SelectValue placeholder="Select an environment…" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="development">Development</SelectItem>
        <SelectItem value="testing">Testing</SelectItem>
        <SelectItem value="staging">Staging</SelectItem>
        <SelectItem value="production">Production</SelectItem>
      </SelectContent>
    </Select>
  </div>
)

export const GroupedOpen = () => (
  <div className="grid w-80 gap-2">
    <Label htmlFor="project-type">Project type</Label>
    <Select defaultOpen defaultValue="http-api">
      <SelectTrigger id="project-type">
        <SelectValue placeholder="Select project type…" />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          <SelectLabel>Services</SelectLabel>
          <SelectItem value="http-api">HTTP API</SelectItem>
          <SelectItem value="consumer">Queue Consumer</SelectItem>
          <SelectItem value="scheduled-job">Scheduled Job</SelectItem>
        </SelectGroup>
        <SelectSeparator />
        <SelectGroup>
          <SelectLabel>Libraries</SelectLabel>
          <SelectItem value="python-library">Python Library</SelectItem>
          <SelectItem value="npm-package">npm Package</SelectItem>
        </SelectGroup>
        <SelectSeparator />
        <SelectItem disabled value="frontend">
          Frontend (archived)
        </SelectItem>
      </SelectContent>
    </Select>
  </div>
)

export const ClosedPlaceholder = () => (
  <div className="grid w-80 gap-2">
    <Label htmlFor="integration-service">Integration</Label>
    <Select>
      <SelectTrigger id="integration-service">
        <SelectValue placeholder="Select an integration…" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="github">GitHub</SelectItem>
        <SelectItem value="pagerduty">PagerDuty</SelectItem>
        <SelectItem value="sentry">Sentry</SelectItem>
      </SelectContent>
    </Select>
  </div>
)

export const ClosedWithValue = () => (
  <div className="grid w-80 gap-2">
    <Label htmlFor="owning-team">Owning team</Label>
    <Select defaultValue="platform">
      <SelectTrigger className="text-sm" id="owning-team">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="platform">Platform Engineering</SelectItem>
        <SelectItem value="data">Data Services</SelectItem>
        <SelectItem value="messaging">Messaging</SelectItem>
      </SelectContent>
    </Select>
  </div>
)

export const Disabled = () => (
  <div className="grid w-80 gap-2">
    <Label htmlFor="cluster">Cluster</Label>
    <Select defaultValue="us-east-1" disabled>
      <SelectTrigger id="cluster">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="us-east-1">us-east-1</SelectItem>
        <SelectItem value="us-west-2">us-west-2</SelectItem>
      </SelectContent>
    </Select>
  </div>
)
