import { ErrorBanner } from 'imbi-ui'

export const Default = () => (
  <div className="max-w-xl w-full">
    <ErrorBanner
      message="The Imbi API returned 503 Service Unavailable."
      title="Failed to load providers"
    />
  </div>
)

export const FromError = () => (
  <div className="max-w-xl w-full">
    <ErrorBanner
      error={new Error('Project imbi-api was not found')}
      title="Failed to load project"
    />
  </div>
)

export const FallbackMessage = () => (
  <div className="max-w-xl w-full">
    <ErrorBanner error={undefined} title="Failed to load user" />
  </div>
)

export const Short = () => (
  <div className="max-w-xl w-full">
    <ErrorBanner message="Clipboard access was denied." title="Copy failed" />
  </div>
)
