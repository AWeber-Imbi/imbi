import { Separator } from 'imbi-ui'

export const Default = () => (
  <div className="w-80">
    <Separator />
  </div>
)

export const BetweenSections = () => (
  <div className="w-96 space-y-6">
    <div>
      <h3 className="text-primary mb-2 text-[16px] font-medium">
        Deployments
      </h3>
      <p className="text-secondary text-sm">
        Notify when imbi-api is deployed to production.
      </p>
    </div>
    <Separator />
    <div>
      <h3 className="text-primary mb-2 text-[16px] font-medium">
        Health & monitoring
      </h3>
      <p className="text-secondary text-sm">
        Alert when project health drops below threshold.
      </p>
    </div>
  </div>
)

export const Vertical = () => (
  <div className="flex h-5 items-center gap-3 text-sm">
    <span className="text-primary">imbi-api</span>
    <Separator orientation="vertical" />
    <span className="text-secondary">production</span>
    <Separator orientation="vertical" />
    <span className="text-secondary">2.35.1</span>
  </div>
)
