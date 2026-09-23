import { useRef, useState } from 'react'

import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'

import type { MarkdownEditorProps } from './MarkdownEditor'
import { MarkdownEditor } from './MarkdownEditor'
import { MarkdownToolbar } from './MarkdownToolbar'
import { useMarkdownFormatting } from './useMarkdownFormatting'

const RELEASE_NOTES = `## Highlights
- Deployments now show **who** promoted each release
- Faster project search (_about 3× on large orgs_)

## Fixes
1. Staging no longer loses its notes on refresh
2. \`imbi-api\` retries AGE connections

> Upgrading from 2.34? See the [upgrade notes](https://example.com).

| Service | Status |
|---|---|
| api | healthy |
| gateway | degraded |
`

/**
 * Holds the draft in local state rather than story args: `updateArgs` is
 * async, so a controlled textarea would briefly re-render the stale value and
 * drop the caret and selection after every keystroke or toolbar click.
 */
function Editable(props: MarkdownEditorProps) {
  const [value, setValue] = useState(props.value)
  return (
    <MarkdownEditor
      {...props}
      onChange={(next) => {
        props.onChange(next)
        setValue(next)
      }}
      value={value}
    />
  )
}

const meta = {
  args: {
    'aria-label': 'Release notes',
    onChange: fn(),
    placeholder: '## Highlights\n- …',
    textareaClassName: 'min-h-40 font-mono text-xs',
    value: '',
  },
  component: MarkdownEditor,
  decorators: [
    (Story) => (
      <div className="w-2xl max-w-full">
        <Story />
      </div>
    ),
  ],
  // Keyed on `value` so editing it in Controls reseeds the draft.
  render: (args) => <Editable key={args.value} {...args} />,
  title: 'UI/MarkdownEditor',
} satisfies Meta<typeof MarkdownEditor>

export default meta

type Story = StoryObj<typeof meta>

export const Empty: Story = {}

export const WithContent: Story = {
  args: { value: RELEASE_NOTES },
}

export const AutoResize: Story = {
  args: {
    autoResize: true,
    textareaClassName: 'min-h-32 max-h-[60vh] font-mono text-xs',
    value: RELEASE_NOTES,
  },
}

export const Disabled: Story = {
  args: { disabled: true, value: RELEASE_NOTES },
}

/**
 * The toolbar on its own, wired to a caller's textarea with
 * `useMarkdownFormatting` — how the document editor uses it alongside its
 * own Split / Write / Preview layout.
 */
export const Toolbar: Story = {
  render: function Render() {
    const [value, setValue] = useState('Select some text and format it.')
    const ref = useRef<HTMLTextAreaElement>(null)
    const { format, onKeyDown } = useMarkdownFormatting(ref, setValue)
    return (
      <div className="border-input rounded-md border">
        <MarkdownToolbar
          className="border-input border-b px-2 py-1"
          onFormat={format}
        />
        <textarea
          className="bg-background block min-h-40 w-full resize-y px-3 py-2 font-mono text-xs outline-none"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          ref={ref}
          value={value}
        />
      </div>
    )
  },
}
