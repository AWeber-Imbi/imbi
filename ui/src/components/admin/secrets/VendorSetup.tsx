import { useQuery } from '@tanstack/react-query'
import { Check, Copy } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { listAIProviders } from '@/api/endpoints'
import { useAgentList } from '@/components/agents/agentQueries'
import { AdminTable } from '@/components/ui/admin-table'
import { Button } from '@/components/ui/button'
import { useClipboard } from '@/hooks/useClipboard'

import { anthropicCondition, openaiMapping } from './wifVendorValues'

interface Props {
  orgId: string
  orgSlug: string
  /** The identity role ARN of the `aws_sts` source, if one is set. */
  roleArn?: string
}

interface Subject {
  id: string
  kind: string
  name: string
  /** The CEL condition or mapping claims, when the role ARN is known. */
  value?: string
}

/**
 * The ids and the ready vendor values for workload identity setup
 * (issue #584): the organization id and ExternalId for the AWS role, and
 * for each agent and AI Provider the Anthropic rule condition or the
 * OpenAI mapping claims.
 */
export function VendorSetup({ orgId, orgSlug, roleArn }: Props) {
  const { copied, copy: writeClipboard } = useClipboard()
  const copy = (text: string, key?: string) =>
    void writeClipboard(text, key).then(
      (ok) => ok || toast.error('Could not copy to the clipboard'),
    )
  const agentsQuery = useAgentList(orgSlug)
  // AI Providers are global; a caller without read access sees none.
  const providersQuery = useQuery({
    queryFn: ({ signal }) => listAIProviders(signal),
    queryKey: ['ai-providers'],
    retry: false,
  })
  // A 403 means no read access, which is expected; other errors are not.
  const failures = [
    { label: 'agents', query: agentsQuery },
    { label: 'AI Providers', query: providersQuery },
  ].filter(
    ({ query }) =>
      query.isError &&
      !(query.error instanceof ApiError && query.error.status === 403),
  )

  const subjects: Subject[] = [
    ...(agentsQuery.data ?? []).map((a) => ({
      id: a.id,
      kind: 'Agent (Anthropic rule)',
      name: a.name,
      value: roleArn && anthropicCondition(roleArn, orgId, 'imbi_agent', a.id),
    })),
    ...(providersQuery.data ?? [])
      .filter((p) => p.driver === 'anthropic' || p.driver === 'openai')
      .map((p) => ({
        id: p.id,
        kind:
          p.driver === 'anthropic'
            ? 'AI Provider (Anthropic rule)'
            : 'AI Provider (OpenAI mapping)',
        name: p.name,
        value:
          roleArn &&
          (p.driver === 'anthropic'
            ? anthropicCondition(roleArn, orgId, 'imbi_ai_provider', p.id)
            : openaiMapping(roleArn, orgId, p.id)),
      })),
  ]
  const externalId = `imbi:${orgId}`

  return (
    <section className="space-y-3">
      <h3 className="text-primary text-sm font-medium">Vendor setup</h3>
      <dl className="grid grid-cols-[max-content_1fr] items-center gap-x-4 gap-y-1 text-sm">
        {[
          ['Organization id', orgId],
          ['ExternalId (role trust policy)', externalId],
        ].map(([label, value]) => (
          <div className="contents" key={label}>
            <dt className="text-secondary">{label}</dt>
            <dd className="flex items-center gap-1 font-mono">
              {value}
              <CopyButton
                copied={copied === value}
                label={`Copy ${label}`}
                onCopy={() => copy(value)}
              />
            </dd>
          </div>
        ))}
      </dl>
      {!roleArn && (
        <p className="text-tertiary text-xs">
          Set an AWS STS identity source to see the rule conditions and the
          mapping claims.
        </p>
      )}
      <AdminTable<Subject>
        columns={[
          { header: 'Name', key: 'name', render: (row) => row.name },
          { header: 'Use', key: 'kind', render: (row) => row.kind },
          {
            header: 'Id',
            key: 'id',
            render: (row) => (
              <span className="flex items-center gap-1 font-mono">
                {row.id}
                <CopyButton
                  copied={copied === `id:${row.id}`}
                  label={`Copy the id of ${row.name}`}
                  onCopy={() => copy(row.id, `id:${row.id}`)}
                />
              </span>
            ),
          },
          {
            header: 'Condition or claims',
            key: 'value',
            render: ({ id, name, value }) =>
              value && (
                <CopyButton
                  copied={copied === `value:${id}`}
                  label={`Copy the vendor values of ${name}`}
                  onCopy={() => copy(value, `value:${id}`)}
                />
              ),
          },
        ]}
        emptyMessage="No agents or Anthropic or OpenAI AI Providers."
        getRowKey={(row) => row.id}
        loading={agentsQuery.isLoading || providersQuery.isLoading}
        rows={subjects}
      />
      {failures.map(({ label, query }) => (
        <p className="text-danger flex items-center gap-2 text-xs" key={label}>
          Could not load the {label}.
          <Button
            onClick={() => void query.refetch()}
            size="sm"
            variant="ghost"
          >
            Retry
          </Button>
        </p>
      ))}
    </section>
  )
}

function CopyButton({
  copied,
  label,
  onCopy,
}: {
  copied: boolean
  label: string
  onCopy: () => void
}) {
  return (
    <Button aria-label={label} onClick={onCopy} size="sm" variant="ghost">
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </Button>
  )
}
