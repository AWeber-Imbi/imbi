import { Rocket } from 'lucide-react'
import { Alert } from 'imbi-ui'

export const Default = () => (
  <div className="max-w-xl w-full">
    <Alert title="Keep your API keys secure" variant="info">
      API keys grant access to your Imbi resources. Never share them or commit
      them to version control.
    </Alert>
  </div>
)

export const Variants = () => (
  <div className="flex max-w-xl w-full flex-col gap-3">
    <Alert variant="info">imbi-api 2.36.0 is queued for staging.</Alert>
    <Alert variant="success">Deployed imbi-api 2.35.1 to production.</Alert>
    <Alert variant="warning">That model no longer exists.</Alert>
    <Alert variant="danger">Failed to save default version formats.</Alert>
  </div>
)

export const WithTitle = () => (
  <div className="max-w-xl w-full">
    <Alert title="CI failed for 6141081" variant="danger">
      <div className="flex flex-col gap-1.5">
        <span className="leading-relaxed">
          The test job exited with status 1 on imbi-api.
        </span>
        <span className="text-xs opacity-80">
          Fix the build before you promote this commit to production.
        </span>
      </div>
    </Alert>
  </div>
)

export const CustomIcon = () => (
  <div className="flex max-w-xl w-full flex-col gap-3">
    <Alert icon={Rocket} title="Promotion ready" variant="success">
      imbi-gateway 2.35.1 passed in staging.
    </Alert>
    <Alert icon={null} variant="warning">
      Deployments to production are frozen until Monday.
    </Alert>
  </div>
)
