import type { ReactNode } from 'react'

import { useQuery } from '@tanstack/react-query'

import { listTeams } from '@/api/endpoints'
import { Combobox } from '@/components/ui/combobox'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'
import { Textarea } from '@/components/ui/textarea'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { queryKeys } from '@/lib/queryKeys'

import type { AgentDraft } from './agentDraft'
import { AgentLabelPicker } from './AgentLabelPicker'

interface OverviewTabProps {
  draft: AgentDraft
  errors: Record<string, string>
  onChange: (patch: Partial<AgentDraft>) => void
  onNameChange: (name: string) => void
  orgSlug: string
}

export function Field({
  children,
  error,
  help,
  htmlFor,
  label,
}: {
  children: ReactNode
  error?: string
  help?: string
  htmlFor?: string
  label: ReactNode
}) {
  return (
    <div>
      <Label className="text-secondary mb-1.5 block text-sm" htmlFor={htmlFor}>
        {label}
      </Label>
      {children}
      {error ? (
        <p className="text-danger mt-1.5 text-xs" role="alert">
          {error}
        </p>
      ) : (
        help && <p className="text-tertiary mt-1.5 text-xs">{help}</p>
      )}
    </div>
  )
}

export function OverviewTab({
  draft,
  errors,
  onChange,
  onNameChange,
  orgSlug,
}: OverviewTabProps) {
  const setIcon = useIconWithCleanup(draft.icon, (icon) => onChange({ icon }))
  const isUpload = draft.icon.startsWith('/') || draft.icon.startsWith('http')
  const { data: teams = [] } = useQuery({
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: queryKeys.teams(orgSlug),
  })

  return (
    <div className="flex max-w-180 flex-col gap-5">
      <Field
        error={errors.name}
        htmlFor="agent-name"
        label={
          <>
            Agent name <RequiredAsterisk />
          </>
        }
      >
        <Input
          id="agent-name"
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="Mender"
          value={draft.name}
        />
      </Field>
      <Field
        help="Shown in the task inbox and the workflow picker."
        htmlFor="agent-description"
        label="Description"
      >
        <Textarea
          id="agent-description"
          onChange={(e) => onChange({ description: e.target.value })}
          placeholder="One sentence on what this agent does."
          rows={3}
          value={draft.description}
        />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Icon">
          <IconPicker onChange={setIcon} value={isUpload ? '' : draft.icon} />
        </Field>
        <Field label="Or upload a custom image">
          <IconUpload
            maxSizeKB={500}
            onChange={setIcon}
            value={isUpload ? draft.icon : ''}
          />
        </Field>
      </div>
      <Field
        help="Where this agent posts updates and asks for input."
        htmlFor="agent-slack"
        label="Slack channel"
      >
        <Input
          id="agent-slack"
          onChange={(e) => onChange({ slackChannel: e.target.value })}
          placeholder="#cs-escalations"
          value={draft.slackChannel}
        />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field
          error={errors.team}
          help="The team that owns this agent."
          htmlFor="agent-team"
          label={
            <>
              Owner team <RequiredAsterisk />
            </>
          }
        >
          <Combobox
            id="agent-team"
            onChange={(team) => onChange({ team })}
            options={teams.map((t) => ({ label: t.name, value: t.slug }))}
            placeholder="Select a team"
            value={draft.team}
          />
        </Field>
        <Field label="Labels">
          <AgentLabelPicker
            onChange={(tags) => onChange({ tags })}
            orgSlug={orgSlug}
            value={draft.tags}
          />
        </Field>
      </div>
    </div>
  )
}
