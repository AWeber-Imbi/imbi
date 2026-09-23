import { useState } from 'react'
import { MarkdownEditor } from 'imbi-ui'

const RELEASE_NOTES = `## Highlights
- Deployments now show **who** promoted each release
- Faster project search (_about 3× on large orgs_)

## Fixes
1. Staging no longer loses its notes on refresh
2. \`imbi-api\` retries AGE connections

> Upgrading from 2.34? See the [upgrade notes](https://example.com).
`

function Editable(props: { autoResize?: boolean; disabled?: boolean; value: string }) {
  const [value, setValue] = useState(props.value)
  return (
    <div className="w-2xl max-w-full">
      <MarkdownEditor
        aria-label="Release notes"
        autoResize={props.autoResize}
        disabled={props.disabled}
        onChange={setValue}
        placeholder={'## Highlights\n- …'}
        textareaClassName="min-h-40 font-mono text-xs"
        value={value}
      />
    </div>
  )
}

export const WithContent = () => <Editable value={RELEASE_NOTES} />
export const Empty = () => <Editable value="" />
export const AutoResize = () => <Editable autoResize value={RELEASE_NOTES} />
export const Disabled = () => <Editable disabled value={RELEASE_NOTES} />
