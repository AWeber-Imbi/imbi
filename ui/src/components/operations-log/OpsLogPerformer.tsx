import { AgentMark } from '@/components/agents/TaskFilterBar'
import { UserIdentity } from '@/components/ui/user-identity'
import type { Agent } from '@/types'

/**
 * Performer avatar for the dense ops-log grid (column 7) — avatar-only with a
 * name tooltip. Shared by the release card and the stream row so both rows
 * attribute their performer identically. An agent performer shows its mark.
 */
export function OpsLogPerformer({
  agent,
  displayName,
  performer,
}: {
  agent?: Agent
  displayName: null | string
  performer: null | string
}) {
  return (
    <span
      className="self-center justify-self-end"
      style={{ gridColumn: 7, gridRow: '1 / -1' }}
      title={displayName ?? undefined}
    >
      {agent ? (
        <AgentMark agent={agent} />
      ) : (
        <UserIdentity
          actor={performer}
          displayName={displayName}
          // Only a real email drives a Gravatar lookup.
          email={performer?.includes('@') ? performer : undefined}
          hideName
          linkToProfile={false}
          size="small"
        />
      )}
    </span>
  )
}
