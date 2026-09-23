import { Label, RequiredAsterisk, Textarea } from 'imbi-ui'

export const Default = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="project-description">Description</Label>
    <Textarea
      className="min-h-30 resize-none"
      id="project-description"
      placeholder="Provide a high-level purpose and context for the project"
    />
  </div>
)

export const Filled = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="ops-description">
      Description <RequiredAsterisk />
    </Label>
    <Textarea
      className="min-h-24 resize-none"
      defaultValue="Rolled imbi-api to 2.35.1 in production after the staging soak. Cleared the stale ClickHouse migration lock first."
      id="ops-description"
    />
  </div>
)

export const AutoResize = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="release-notes">Release notes</Label>
    <Textarea
      autoResize
      className="max-h-60"
      id="release-notes"
      value={
        '## Fixes\n- Create the email_audit ClickHouse table\n- Sign release tags\n\n## Features\n- Markdown editor for release notes'
      }
      readOnly
    />
  </div>
)

export const Invalid = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="incident-summary">
      Summary <RequiredAsterisk />
    </Label>
    <Textarea
      aria-invalid
      className="min-h-24 resize-none border-red-500"
      id="incident-summary"
      placeholder="Short summary of what was done"
    />
    <p className="text-sm text-red-600">Summary is required</p>
  </div>
)

export const Disabled = () => (
  <div className="w-80 space-y-2">
    <Label htmlFor="archived-notes">Notes</Label>
    <Textarea
      className="resize-none"
      defaultValue="This project is archived. Notes are read-only."
      disabled
      id="archived-notes"
    />
  </div>
)
