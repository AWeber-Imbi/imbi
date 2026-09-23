import { ConfirmDialog } from 'imbi-ui'

const noop = () => {}

export const DeleteEnvironment = () => (
  <ConfirmDialog
    description="Projects deployed to staging lose their staging URLs and deployment history. This action cannot be undone."
    onCancel={noop}
    onConfirm={noop}
    open
    title="Delete the staging environment?"
  />
)

export const RemoveIntegration = () => (
  <ConfirmDialog
    confirmLabel="Remove integration"
    description="imbi-api stops syncing commits, tags, and releases from GitHub."
    onCancel={noop}
    onConfirm={noop}
    open
    title="Remove the GitHub integration?"
  />
)

export const DefaultDescription = () => (
  <ConfirmDialog
    onCancel={noop}
    onConfirm={noop}
    open
    title="Delete the platform-team team?"
  />
)
