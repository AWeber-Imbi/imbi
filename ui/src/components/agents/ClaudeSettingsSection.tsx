import { useQuery } from '@tanstack/react-query'

import { getAgentPlatformConfig } from '@/api/endpoints'
import { Textarea } from '@/components/ui/textarea'
import { queryKeys } from '@/lib/queryKeys'

import { SETTINGS_HELP, type SettingsDraft, settingsText } from './agentDraft'
import { Field } from './OverviewTab'

interface ClaudeSettingsSectionProps {
  error?: string
  onChange: (settings: SettingsDraft) => void
  orgSlug: string
  value: SettingsDraft
}

/**
 * The agent's Claude Code settings. Each key that the agent sets
 * replaces the organization's value, unless the organization enforces
 * it. Agent hooks need Bash with no limit in the organization.
 */
export function ClaudeSettingsSection({
  error,
  onChange,
  orgSlug,
  value,
}: ClaudeSettingsSectionProps) {
  const config = useQuery({
    queryFn: ({ signal }) => getAgentPlatformConfig(orgSlug, signal),
    queryKey: queryKeys.agentPlatformConfig(orgSlug),
  })
  const org = settingsText(config.data?.config.claude_settings)
  const enforced = config.data?.config.enforced ?? []

  return (
    <section className="flex flex-col gap-3">
      <div className="text-overline text-tertiary uppercase">
        Claude Code settings
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Field
          error={error}
          help={SETTINGS_HELP}
          htmlFor="agent-claude-settings"
          label="Agent"
        >
          <Textarea
            className="font-mono text-xs"
            id="agent-claude-settings"
            onChange={(e) =>
              onChange({ ...value, claudeSettings: e.target.value })
            }
            placeholder="{}"
            rows={8}
            value={value.claudeSettings}
          />
        </Field>
        <Field
          help={
            enforced.length
              ? `Enforced, agents cannot set: ${enforced.join(', ')}`
              : 'The organization enforces no key.'
          }
          label="Organization"
        >
          <pre className="h-41 overflow-auto rounded-md border border-tertiary bg-secondary p-2 font-mono text-xs text-secondary">
            {org || 'None'}
          </pre>
        </Field>
      </div>
    </section>
  )
}
