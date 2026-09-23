import { Input, Label, SavedIndicator } from 'imbi-ui'

export const AfterSave = () => (
  <div className="flex w-96 items-center gap-3">
    <Label className="w-24 text-sm" htmlFor="env-production-url">
      URL
    </Label>
    <div className="relative flex-1">
      <Input
        className="pr-8 text-sm"
        defaultValue="https://imbi.aweber.io"
        id="env-production-url"
      />
      <SavedIndicator show />
    </div>
  </div>
)

export const Hidden = () => (
  <div className="flex w-96 items-center gap-3">
    <Label className="w-24 text-sm" htmlFor="env-staging-url">
      URL
    </Label>
    <div className="relative flex-1">
      <Input
        className="pr-8 text-sm"
        defaultValue="https://imbi.staging.aweber.io"
        id="env-staging-url"
      />
      <SavedIndicator show={false} />
    </div>
  </div>
)

export const EnvironmentFields = () => (
  <div className="flex w-96 flex-col gap-3">
    <div className="text-primary text-sm font-medium">production</div>
    <div className="flex items-center gap-3">
      <Label className="w-24 text-sm" htmlFor="env-prod-url">
        URL
      </Label>
      <div className="relative flex-1">
        <Input
          className="pr-8 text-sm"
          defaultValue="https://imbi.aweber.io"
          id="env-prod-url"
        />
        <SavedIndicator show />
      </div>
    </div>
    <div className="flex items-center gap-3">
      <Label className="w-24 text-sm" htmlFor="env-prod-dashboard">
        Dashboard
      </Label>
      <div className="relative flex-1">
        <Input
          className="pr-8 text-sm"
          id="env-prod-dashboard"
          placeholder="Dashboard"
        />
        <SavedIndicator show={false} />
      </div>
    </div>
  </div>
)
