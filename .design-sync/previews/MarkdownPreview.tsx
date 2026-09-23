import { MarkdownPreview } from 'imbi-ui'

const RELEASE_NOTES = `## Highlights
- Deployments now show **who** promoted each release
- Faster project search (_about 3× on large orgs_)

## Fixes
1. Staging no longer loses its notes on refresh
2. \`imbi-api\` retries AGE connections

\`\`\`bash
uv run imbi-api migrate --to 2.35.0
\`\`\`

> Upgrading from 2.34? See the [upgrade notes](https://example.com).

| Service | Status |
|---|---|
| api | healthy |
| gateway | degraded |
`

const OPS_NOTE = `### Rollback: imbi-gateway 2.35.1

Rolled **production** back to \`2.35.0\` after 5xx rates rose above 2%.

- [x] Traffic drained from the new pods
- [x] Previous image redeployed
- [ ] Root cause posted to #platform-incidents
`

export const ReleaseNotes = () => (
  <div className="w-full max-w-xl">
    <MarkdownPreview value={RELEASE_NOTES} />
  </div>
)

export const OpsLogNote = () => (
  <div className="w-full max-w-xl">
    <MarkdownPreview value={OPS_NOTE} />
  </div>
)

export const Empty = () => (
  <div className="w-full max-w-xl">
    <MarkdownPreview value="" />
  </div>
)
